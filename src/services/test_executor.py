"""Save and execute generated Python tests with pytest."""

import asyncio
import subprocess
import sys
import time
from pathlib import Path

from src.utils.logger import create_logger
from src.utils.locale import SEVERITIES, TEST_TYPES, display_label

logger = create_logger("test-executor")


class TestExecutor:
    def __init__(self, config=None):
        self.config = {"dryRun": False, "parallel": False, "maxConcurrency": 4,
                       "timeout": 30000, "retryCount": 2, **(config or {})}

    async def save_tests(self, tests):
        saved_files = []
        logger.info(f"正在保存 {len(tests)} 个生成的测试")
        for test in tests:
            try:
                file_path = test["filePath"]
                path = Path(file_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(test["content"], encoding="utf-8")
                saved_files.append(file_path)
                logger.info(f"已保存测试：{test['name']} → {file_path}")
            except Exception as error:
                logger.error(f"保存测试 {test['name']} 失败：", error)
        return saved_files

    async def execute_tests(self, tests):
        if self.config["dryRun"]:
            logger.info("试运行模式：跳过测试执行")
            return [{"test": test, "success": True,
                     "output": "试运行：已跳过测试执行", "executionTime": 0}
                    for test in tests]
        logger.info(f"正在执行 {len(tests)} 个测试")
        if self.config["parallel"]:
            return await self.execute_tests_parallel(tests)
        return await self.execute_tests_sequential(tests)

    async def execute_tests_sequential(self, tests):
        results = []
        for test in tests:
            results.append(await self.execute_single_test(test))
        return results

    async def execute_tests_parallel(self, tests):
        results = []
        for chunk in self.chunk_array(tests, self.config["maxConcurrency"]):
            results.extend(await asyncio.gather(*(self.execute_single_test(test) for test in chunk)))
        return results

    async def execute_single_test(self, test):
        start_time = time.time() * 1000
        last_error = None
        logger.info(f"正在执行测试：{test['name']}")
        for attempt in range(1, self.config["retryCount"] + 2):
            try:
                proc = await asyncio.to_thread(
                    subprocess.run, [sys.executable, "-m", "pytest", "-q", test["filePath"]],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                    timeout=self.config["timeout"] / 1000, check=True)
                return {"test": test, "success": True, "output": proc.stdout,
                        "executionTime": int(time.time() * 1000 - start_time)}
            except Exception as error:
                last_error = error
                if attempt <= self.config["retryCount"]:
                    logger.warn(f"测试 {test['name']} 第 {attempt} 次失败，正在重试……")
                    await self.delay(1000 * attempt)
        stdout = getattr(last_error, "stdout", None) or getattr(last_error, "output", None) or b""
        return {"test": test, "success": False,
                "output": stdout.decode(errors="replace") if isinstance(stdout, bytes) else str(stdout),
                "error": str(last_error), "executionTime": int(time.time() * 1000 - start_time)}

    def chunk_array(self, array, chunk_size):
        return [array[i:i + chunk_size] for i in range(0, len(array), chunk_size)]

    async def delay(self, ms):
        await asyncio.sleep(ms / 1000)

    def display_test_title(self, test):
        description = str(test.get("description") or "").strip()
        return description if any("\u4e00" <= char <= "\u9fff" for char in description) else "端到端测试"

    def generate_test_report(self, results):
        total_tests = len(results)
        passed_tests = len([r for r in results if r["success"]])
        failed_tests = total_tests - passed_tests
        total_time = sum(r["executionTime"] for r in results)
        success_rate = passed_tests / total_tests * 100 if total_tests else 0.0
        report = ("# 测试执行报告\n\n**摘要：**\n"
                  f"- 测试总数：{total_tests}\n- 通过：{passed_tests}\n- 失败：{failed_tests}\n"
                  f"- 通过率：{success_rate:.1f}%\n- 总耗时：{total_time} 毫秒\n\n")
        if failed_tests > 0:
            report += "## 失败的测试\n\n"
            for index, result in enumerate((r for r in results if not r["success"]), 1):
                test = result["test"]
                report += (f"### {index}. {self.display_test_title(test)}\n"
                           f"- **测试标识：** `{test['name']}`\n"
                           f"- **类型：** {display_label(test['testType'], TEST_TYPES)}\n"
                           f"- **优先级：** {display_label(test['priority'], SEVERITIES)}\n- **文件：** {test['filePath']}\n"
                           f"- **错误摘要：** 测试执行失败\n"
                           f"- **原始错误：** {result.get('error') or '未知错误'}\n\n")
        report += "## 全部测试结果\n\n"
        for result in results:
            test = result["test"]
            status = "✅" if result["success"] else "❌"
            report += (f"{status} **{self.display_test_title(test)}**（{result['executionTime']} 毫秒）\n"
                       f"- 测试标识：`{test['name']}`\n"
                       f"- 类型：{display_label(test['testType'], TEST_TYPES)}，优先级：{display_label(test['priority'], SEVERITIES)}\n"
                       f"- 文件：{test['filePath']}\n\n")
        return report

    async def save_test_report(self, results, output_path):
        report = self.generate_test_report(results)
        try:
            Path(output_path).write_text(report, encoding="utf-8")
            logger.info(f"测试报告已保存至：{output_path}")
        except Exception as error:
            logger.error("保存测试报告失败：", error)

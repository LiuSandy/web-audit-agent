"""TypeScript interfaces from src/types/index.ts, with original field names."""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict


class OrderedSet(set[str]):
    """JavaScript Set iteration order for serialized visitedUrls."""

    def __init__(self, values=()):
        super().__init__()
        self._order: list[str] = []
        for value in values:
            self.add(value)

    def add(self, value: str) -> None:
        if value not in self:
            self._order.append(value)
        super().add(value)

    def discard(self, value: str) -> None:
        if value in self:
            self._order.remove(value)
        super().discard(value)

    def remove(self, value: str) -> None:
        self._order.remove(value)
        super().remove(value)

    def clear(self) -> None:
        self._order.clear()
        super().clear()

    def __iter__(self):
        return iter(self._order)


class AgentFinding(TypedDict):
    type: Literal[
        "broken_image", "console_error", "network_error", "validation_error",
        "functional_bug", "ux_issue", "bug", "layout", "other",
    ]
    description: str
    url: str
    severity: Literal["low", "medium", "high", "critical"]
    selector: NotRequired[str]
    category: NotRequired[Literal["layout", "functional", "visual", "performance", "security", "other"]]
    screenshot: NotRequired[str]
    metadata: NotRequired[dict[str, Any]]
    occurrences: NotRequired[list[str]]
    count: NotRequired[int]


class AgentHistory(TypedDict):
    action: str
    reason: str
    url: str
    result: NotRequired[str]
    params: NotRequired[Any]


class AgentState(TypedDict):
    visitedUrls: OrderedSet
    findings: list[AgentFinding]
    steps: int
    history: list[AgentHistory]
    todoQueue: list[str]


class AuthCredentials(TypedDict):
    password: str
    username: NotRequired[str]
    email: NotRequired[str]
    totpSecret: NotRequired[str]


class AuthOptions(TypedDict):
    required: bool
    appIdentifier: str
    autoLogin: NotRequired[bool]
    credentials: NotRequired[AuthCredentials]


class AgentConfig(TypedDict):
    baseUrl: str
    maxSteps: NotRequired[int]
    model: NotRequired[Any]
    sessionId: NotRequired[str]
    auth: NotRequired[AuthOptions]
    enableTestGeneration: NotRequired[bool]
    testOutputDir: NotRequired[str]
    includeE2ETests: NotRequired[bool]
    testDryRun: NotRequired[bool]
    testParallelExecution: NotRequired[bool]
    testMaxConcurrency: NotRequired[int]
    testTimeout: NotRequired[int]
    testRetryCount: NotRequired[int]


class Location(TypedDict):
    x: int | float
    y: int | float


class BrokenImageFinding(TypedDict):
    src: str
    alt: str
    selector: str
    reason: str
    location: Location
    srcset: NotRequired[str]


class ViewportConfig(TypedDict):
    width: int
    height: int
    name: str


class VisualRegressionConfig(TypedDict):
    enabled: bool
    baselineDir: str
    currentDir: str
    diffDir: str
    viewports: list[ViewportConfig]
    threshold: float
    pixelmatchThreshold: float
    captureFullPage: bool
    generateDiffImages: bool


class VisualRegressionResult(TypedDict):
    url: str
    viewport: ViewportConfig
    baselineExists: bool
    currentPath: str
    match: bool
    diffPercentage: float
    diffPixelCount: int
    isNewBaseline: bool
    baselinePath: NotRequired[str]
    diffPath: NotRequired[str]


class LayoutScreenshotConfig(TypedDict):
    enabled: bool
    outputDir: NotRequired[str]
    highlightElements: NotRequired[bool]
    type: NotRequired[Literal["png", "jpeg"]]


class LayoutAuditConfig(TypedDict):
    enabled: bool
    maxElements: int
    heuristics: list[str]
    screenshots: NotRequired[LayoutScreenshotConfig]


class LayoutAuditFinding(TypedDict):
    type: str
    severity: Literal["error", "warning", "info"]
    category: Literal["layout", "visual", "other"]
    message: str
    selector: NotRequired[str]
    screenshot: NotRequired[str]
    fullPageScreenshot: NotRequired[str]


class SinglePageTestConfig(TypedDict):
    targetUrl: str
    maxTestCases: NotRequired[int]
    model: NotRequired[Any]
    sessionId: NotRequired[str]
    strategy: NotRequired[Literal["comprehensive", "critical-path", "edge-cases"]]
    auth: NotRequired[AuthOptions]
    layoutAudit: NotRequired[LayoutAuditConfig]
    visualRegression: NotRequired[VisualRegressionConfig]


class TestStep(TypedDict):
    action: Literal["click", "fill", "select", "hover", "wait", "verify", "navigate"]
    description: str
    selector: NotRequired[str]
    value: NotRequired[str]
    condition: NotRequired[str]


class TestCase(TypedDict):
    id: str
    name: str
    description: str
    priority: Literal["critical", "high", "medium", "low"]
    category: Literal["form", "navigation", "interaction", "validation", "visual"]
    steps: list[TestStep]
    expectedOutcome: str
    preconditions: NotRequired[list[str]]


class PageCoverage(TypedDict):
    forms: int
    buttons: int
    links: int
    inputs: int
    otherInteractive: int


class TestPlan(TypedDict):
    pageUrl: str
    pageTitle: str
    totalTests: int
    estimatedDurationSeconds: int
    coverage: PageCoverage
    testCases: list[TestCase]


class TestCaseResult(TypedDict):
    testCaseId: str
    status: Literal["passed", "failed", "skipped", "error"]
    executionTimeMs: int
    stepsExecuted: int
    findings: list[AgentFinding]
    actualOutcome: NotRequired[str]
    errorMessage: NotRequired[str]


class SinglePageTestState(TypedDict):
    sessionId: str
    testPlan: TestPlan | None
    results: list[TestCaseResult]
    currentTestIndex: int
    status: Literal["planning", "executing", "completed", "failed", "stopped"]
    currentAction: str
    lastError: str | None
    startTime: int
    endTime: NotRequired[int]


class DiscoveredElement(TypedDict):
    tag: str
    selector: str
    text: str
    attributes: dict[str, str | None]
    isVisible: bool
    interactable: bool
    type: NotRequired[str]

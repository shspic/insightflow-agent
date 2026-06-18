import importlib


SERVICE_MODULES = [
    "app.services.file_service",
    "app.services.parser_service",
    "app.services.analysis_service",
    "app.services.chart_service",
    "app.services.rag_service",
    "app.services.report_service",
    "app.services.llm_service",
]


def test_core_service_modules_can_import() -> None:
    for module_name in SERVICE_MODULES:
        module = importlib.import_module(module_name)
        assert module is not None

# API Reference — pytest Plugin

RAMPART's pytest integration. Activates automatically when installed.

::: rampart.pytest_plugin._collection
    options:
      members:
        - record_result
        - ResultCollectionHandler
        - ResultCollector

::: rampart.pytest_plugin._session
    options:
      members:
        - RampartSession
        - TrialGroupResult

## Parallel Execution Hooks

When `pytest-xdist` is installed, the plugin streams Result envelopes on call
reports, with a non-passing setup fallback when no call report will occur,
through `pytest_runtest_logreport`. It uses the optional `pytest_testnodedown`
hook to reconcile per-worker Result counts. See
[Parallel Execution](../usage/xdist.md) for the data flow and trust boundary.

::: rampart.pytest_plugin._xdist
    options:
      members:
        - SCHEMA_VERSION
        - WORKEROUTPUT_KEY
        - SIZE_LIMIT_OPTION
        - DEFAULT_SIZE_LIMIT_BYTES
        - MIN_RESULT_SIZE_LIMIT_BYTES
        - WorkerOutputError
        - SchemaVersionError
        - SizeLimitError
        - is_xdist_worker
        - is_xdist_controller
        - get_dist_mode
        - get_worker_count
        - attach_report_results
        - serialize_report_data
        - deserialize_report_data
        - merge_report_results
        - serialize_worker_data
        - deserialize_trial_specs
        - finalize_worker
        - handle_testnodedown
        - discover_sinks_from_conftest

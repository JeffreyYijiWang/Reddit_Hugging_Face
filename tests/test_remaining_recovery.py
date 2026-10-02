import importlib.util
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    'reddit_reid._remaining_recovery_test',
    Path(__file__).resolve().parents[1] / 'tools' / 'remaining_runner.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


@pytest.mark.parametrize('error_type', [BrokenProcessPool, runner.duckdb.OutOfMemoryException])
def test_worker_crash_resumes_same_configuration_without_export(monkeypatch, error_type):
    cfg = {'resources': {}, 'workflow': {'automatic_full_run_restart_attempts': 2}}
    calls, states = [], []

    def scan(received, max_files):
        assert received is cfg
        assert max_files is None
        calls.append(received)
        if len(calls) == 1:
            raise error_type('simulated worker failure')
        return {'complete': True}

    monkeypatch.setattr(runner, 'scan_parallel', scan)
    monkeypatch.setattr(runner, 'save_json', lambda path, status: states.append(dict(status)))
    monkeypatch.setattr(runner.time, 'sleep', lambda seconds: None)
    status = {}
    assert runner.scan_with_recovery(cfg, None, status, Path('unused')) == {'complete': True}
    assert len(calls) == 2
    assert status['automatic_restarts'] == 1
    assert any(s['state'] == 'recovering_scan' for s in states)
    assert states[-1]['state'] == 'running'


def test_restart_budget_is_shared_across_passes(monkeypatch):
    calls = []

    def scan(*args, **kwargs):
        calls.append(True)
        raise BrokenProcessPool('simulated repeated failure')

    monkeypatch.setattr(runner, 'scan_parallel', scan)
    monkeypatch.setattr(runner, 'save_json', lambda *args: None)
    monkeypatch.setattr(runner.time, 'sleep', lambda seconds: None)
    status = {'automatic_restarts': 1}
    with pytest.raises(BrokenProcessPool):
        runner.scan_with_recovery({'resources': {}, 'workflow': {'automatic_full_run_restart_attempts': 2}},
                                  None, status, Path('unused'))
    assert len(calls) == 2
    assert status['automatic_restarts'] == 2
    assert status['recoverable_failures'][-1]['restart_available'] is False


def test_unrelated_failures_are_not_retried(monkeypatch):
    def scan(*args, **kwargs):
        raise OSError('simulated drive error')

    monkeypatch.setattr(runner, 'scan_parallel', scan)
    monkeypatch.setattr(runner, 'save_json', lambda *args: None)
    status = {}
    with pytest.raises(OSError):
        runner.scan_with_recovery({'resources': {}, 'workflow': {}}, None, status, Path('unused'))
    assert 'automatic_restarts' not in status


def test_memory_wait_resumes_when_headroom_returns(monkeypatch, tmp_path):
    values = iter([100, 1000])
    states, waits = [], []
    monkeypatch.setattr(runner, 'allocation_headroom', lambda: next(values))
    monkeypatch.setattr(runner, 'save_json', lambda path, status: states.append(dict(status)))
    monkeypatch.setattr(runner.time, 'sleep', waits.append)
    status = {}
    runner.wait_for_memory({'resources': {'minimum_query_memory_bytes': 500},
                            'data_root': str(tmp_path)}, status, tmp_path/'state.json')
    assert waits == [10]
    assert states[0]['state'] == 'waiting_for_memory'
    assert status['state'] == 'running'

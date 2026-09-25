from tools.avoid_duplicate_discovery import decision


def test_context_must_finish_before_discovery_stop():
    supervisor = {'pid': 123, 'state': 'collecting_archived_context'}
    context = {'started_at': 'expected', 'active': True}
    assert decision(supervisor, context, 123, 'expected') == 'waiting_for_context'
    context.update(active=False)
    assert decision(supervisor, context, 123, 'expected') == 'waiting_for_context'
    context['finished_at'] = 'done'
    assert decision(supervisor, context, 123, 'expected') == 'skip_duplicate_discovery'


def test_other_and_ended_runs_are_never_stopped():
    supervisor = {'pid': 123, 'state': 'collecting_archived_context'}
    context = {'started_at': 'expected', 'active': False, 'finished_at': 'done'}
    assert decision(supervisor, context, 124, 'expected') == 'different_supervisor'
    assert decision(supervisor, context, 123, 'different') == 'different_context_run'
    supervisor['state'] = 'failed_or_interrupted'
    assert decision(supervisor, context, 123, 'expected') == 'supervisor_ended'

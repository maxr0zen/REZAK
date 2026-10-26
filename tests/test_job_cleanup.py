from rezak.jobs import JobRunner
from rezak.store import Store

def test_cancel_stops_analysis_and_refinement_without_touching_other_jobs(tmp_path,monkeypatch):
    runner=JobRunner(Store(tmp_path/'app'),tmp_path);calls=[]
    monkeypatch.setattr('rezak.jobs.subprocess.run',lambda command,**kwargs:calls.append(command))
    runner.cleanup_gpu('fixture')
    assert calls[0]==['docker','stop','--time','5','rezak-asr-fixture','rezak-asr-setup-fixture','rezak-analysis-fixture','rezak-refine-fixture']
    runner.owners.add('fixture');runner.cleanup_gpu('fixture')
    assert calls[1][-1]=='rezak-bonsai-1' and 'fixture' not in runner.owners

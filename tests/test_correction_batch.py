import json
from pathlib import Path

import pytest
from scripts.correction_batch import plan, main, STILLS, CLIPS


def test_fixture_matrix_has_all_96_conditions(tmp_path):
    fixture=tmp_path/"fixture.png";fixture.touch()
    jobs=plan("fixture",tmp_path,fixture)
    assert len(jobs)==16 and len({name for name,_ in jobs})==16
    assert sum(len(args[args.index(next(v for v in args if v.startswith('--sweep-target-')))+1].split(',')) for _,args in jobs)==96


def test_po_batch_preflight_and_default_settings(tmp_path):
    with pytest.raises(ValueError,match="Missing/ambiguous"):
        plan("po",tmp_path,Path("unused"))
    for stem in STILLS: (tmp_path/(stem+".jpg")).touch()
    for stem in CLIPS: (tmp_path/(stem+".mp4")).touch()
    jobs=plan("po",tmp_path,Path("unused"),True)
    assert len(jobs)==11
    assert all("--unmirror" in args and "--effective-strength" not in args and "--set" not in args for _,args in jobs)


def test_batch_never_fabricates_gate_and_preserves_failure(tmp_path):
    fixture=tmp_path/"fixture.png";fixture.touch()
    calls=[]
    def run(args): calls.append(args);return int(len(calls)==3)
    args=["fixture","--fixture",str(fixture),"--out",str(tmp_path),"--name","batch"]
    assert main(args,runner=run)==1 and len(calls)==16
    report=json.loads((tmp_path/"batch"/"batch.json").read_text())
    assert report["visual_gate"]=="NOT EVALUATED"
    assert sum(x["exit_code"] for x in report["experiments"])==1
    assert len((tmp_path/"batch"/"scores.csv").read_text().splitlines())==17
    with pytest.raises(SystemExit): main(args,runner=run)

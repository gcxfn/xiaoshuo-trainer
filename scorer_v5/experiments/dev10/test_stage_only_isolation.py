#!/usr/bin/env python3
"""Offline isolation tests for Smoke5 staging-only execution boundary.

No model/API/HTTP. No .env reads. Does not write into frozen r3 / draft6 / draft7 runs.
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXP = Path(__file__).resolve().parent
STAGE_PY = EXP / "stage_only_exec.py"
RUNNER = EXP / "run_dev10.py"
SPECS_DIR = ROOT / "scorer_v5" / "specs"
CONFIG_SRC = ROOT / "scorer_v5" / "config" / "formal_model.yaml"
FROZEN_RUNS = (
    EXP / "runs" / "dev10_v5_r3",
    EXP / "runs" / "dev10_v5_r3_draft6_rerun",
    EXP / "runs" / "dev10_v5_r3_draft7_smoke",
)
RECORDED_SUMMARY_SHA = {
    "dev10_v5_r3": "d512c171fcdbab67a5be9ec8f6d443d6dde7c922ae2df69b4909f42f94cfd914",
    "dev10_v5_r3_draft6_rerun": "63b4073a9d6b1f33451055dc0d682043e1b934439bcc9b587c984ece9a78ef65",
}

import importlib.util

_spec = importlib.util.spec_from_file_location("dev10_stage_only_exec", STAGE_PY)
_mod = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_mod)

StageBoundaryError = _mod.StageBoundaryError
validate_stage_bundle = _mod.validate_stage_bundle
build_call_payload = _mod.build_call_payload
load_staged_config = _mod.load_staged_config
execute_stage_card = _mod.execute_stage_card
launch_stage_child = _mod.launch_stage_child
sanitize_child_env = _mod.sanitize_child_env
fan_in_staging_outputs = _mod.fan_in_staging_outputs
classify_status = _mod.classify_status
env_key_forbidden = _mod.env_key_forbidden
write_staged_raw = _mod.write_staged_raw

_RUN_SPEC = importlib.util.spec_from_file_location("dev10_run_dev10", RUNNER)
_RUN = importlib.util.module_from_spec(_RUN_SPEC)
assert _RUN_SPEC and _RUN_SPEC.loader
_RUN_SPEC.loader.exec_module(_RUN)


def _sha256_file(p: Path) -> str:
    return sha256(p.read_bytes()).hexdigest()


def _make_stage(tmp: Path, *, temp_override: float | None = None) -> dict[str, Path]:
    root = tmp / "runs" / "isolation_unit" / "staging" / "bookX" / "B01" / "rep1"
    text_dir = root / "text"
    specs = root / "specs"
    cfg_dir = root / "config"
    out = root / "output"
    for d in (text_dir, specs, cfg_dir, out):
        d.mkdir(parents=True, exist_ok=True)
    (text_dir / "canonical.txt").write_text("主角推开门。\n第二句。\n", encoding="utf-8")
    for y in sorted(SPECS_DIR.glob("*.yaml")):
        shutil.copy2(y, specs / y.name)
    cfg_text = CONFIG_SRC.read_text(encoding="utf-8")
    if temp_override is not None:
        import re

        cfg_text = re.sub(
            r"temperature:\s*[0-9.]+",
            f"temperature: {temp_override}",
            cfg_text,
            count=1,
        )
    (cfg_dir / "formal_model.yaml").write_text(cfg_text, encoding="utf-8")
    return {
        "root": root,
        "text": text_dir / "canonical.txt",
        "specs": specs,
        "config": cfg_dir / "formal_model.yaml",
        "output": out,
    }


class IsolationTests(unittest.TestCase):
    def test_payload_uses_staged_config_not_root_values(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            stage = _make_stage(Path(td), temp_override=0.0)
            # Distinct decoy that must not drive the payload.
            decoy = Path(td) / "decoy_formal_model.yaml"
            decoy.write_text(
                "provider: commandcode\nmodel: deepseek/deepseek-v4-flash\ntemperature: 0.77\ntop_p: 0.3\nseed: 99\nmax_tokens: 11\n",
                encoding="utf-8",
            )
            cfg = load_staged_config(stage["config"])
            payload = build_call_payload("hello-prompt", cfg)
            self.assertEqual(payload["model"], cfg["model"])
            self.assertEqual(payload["temperature"], float(cfg["temperature"]))
            self.assertEqual(payload["top_p"], float(cfg["top_p"]))
            self.assertEqual(payload["seed"], int(cfg["seed"]))
            self.assertNotEqual(payload["temperature"], 0.77)
            self.assertNotEqual(payload["seed"], 99)
            rec = execute_stage_card(
                staging_root=stage["root"],
                book_id="bookX",
                metric="B01",
                rep=1,
                run_id="isolation_unit",
                transport=None,
                allow_http=False,
            )
            self.assertEqual(rec["status"], "PAYLOAD_ONLY")
            self.assertEqual(rec.get("http"), 0)
            saved = json.loads((stage["output"] / "call_payload.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["meta"]["source"], "staged_config")
            self.assertEqual(saved["meta"]["config_path"], str(stage["config"].resolve()))
            self.assertEqual(saved["body"]["temperature"], payload["temperature"])
            self.assertEqual(saved["body"]["model"], "deepseek/deepseek-v4-flash")

    def test_output_confinement_and_mock_transport(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            stage = _make_stage(base)
            cards_probe = base / "runs" / "isolation_unit" / "cards"

            def transport(prompt: str, cfg: dict):
                self.assertEqual(cfg["model"], "deepseek/deepseek-v4-flash")
                return "{not-json", {"http_status": 0, "mock": True}

            rec = execute_stage_card(
                staging_root=stage["root"],
                book_id="bookX",
                metric="B01",
                rep=1,
                run_id="isolation_unit",
                transport=transport,
                allow_http=False,
            )
            self.assertIn(rec["status"], {"FAIL_PARSE", "BLOCKED", "SCHEMA_FAIL"})
            out = stage["output"]
            for name in (
                "preflight.json",
                "prompt.txt",
                "call_payload.json",
                "raw.txt",
                "http_meta.json",
                "provenance.json",
                "result.json",
            ):
                self.assertTrue((out / name).is_file(), msg=name)
            self.assertFalse(cards_probe.exists())
            # no artifact outside staging output except staging inputs
            written_results = list(base.rglob("result.json"))
            self.assertEqual(len(written_results), 1)
            self.assertEqual(written_results[0].resolve(), (out / "result.json").resolve())

    def test_reject_unapproved_paths(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            stage = _make_stage(Path(td))
            cases = [
                ("text", ROOT, stage["specs"], stage["config"], stage["output"]),
                (
                    "text",
                    ROOT / "corpus",
                    stage["specs"],
                    stage["config"],
                    stage["output"],
                ),
                (
                    "output",
                    stage["text"],
                    stage["specs"],
                    stage["config"],
                    ROOT / "scorer_v5" / "experiments" / "dev10" / "runs" / "dev10_v5_r3",
                ),
            ]
            for label, text, specs, config, output in cases:
                with self.subTest(label=label, path=str(text if label == "text" else output)):
                    with self.assertRaises(StageBoundaryError):
                        validate_stage_bundle(
                            staging_root=stage["root"],
                            text=text,
                            specs=specs,
                            config=config,
                            output=output,
                        )
            # CLI reject
            proc = subprocess.run(
                [
                    sys.executable,
                    str(STAGE_PY),
                    "--staging-root",
                    str(ROOT),
                    "--text",
                    str(ROOT / "corpus"),
                    "--specs",
                    str(SPECS_DIR),
                    "--config",
                    str(CONFIG_SRC),
                    "--output",
                    str(ROOT),
                    "--book-id",
                    "x",
                    "--metric",
                    "B01",
                    "--rep",
                    "1",
                    "--run-id",
                    "nope",
                    "--no-http",
                ],
                capture_output=True,
                text=True,
                cwd=str(Path(td)),
            )
            self.assertEqual(proc.returncode, 2)
            blob = (proc.stderr + proc.stdout).lower()
            self.assertTrue(
                "forbidden" in blob or "staging_root must match" in blob or "escapes" in blob or "child cwd" in blob,
                msg=blob,
            )

    def test_subprocess_no_http_writes_only_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            stage = _make_stage(Path(td))
            proc = subprocess.run(
                [
                    sys.executable,
                    str(STAGE_PY),
                    "--staging-root",
                    str(stage["root"]),
                    "--text",
                    str(stage["text"]),
                    "--specs",
                    str(stage["specs"]),
                    "--config",
                    str(stage["config"]),
                    "--output",
                    str(stage["output"]),
                    "--book-id",
                    "bookX",
                    "--metric",
                    "B01",
                    "--rep",
                    "1",
                    "--run-id",
                    "isolation_unit",
                    "--no-http",
                ],
                capture_output=True,
                text=True,
                cwd=str(stage["root"]),
                env=sanitize_child_env(),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["http"], 0)
            rec = json.loads((stage["output"] / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(rec["status"], "BLOCKED")
            self.assertEqual(rec.get("reason"), "missing_raw")
            self.assertFalse((Path(td) / "cards").exists())

    def test_frozen_summaries_unchanged(self) -> None:
        for run_id, expected in RECORDED_SUMMARY_SHA.items():
            p = EXP / "runs" / run_id / "summary.json"
            self.assertTrue(p.is_file(), msg=str(p))
            self.assertEqual(_sha256_file(p), expected, msg=run_id)

    def test_live_child_pid_cwd_env_audit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            stage = _make_stage(Path(td))
            poisoned = dict(os.environ)
            poisoned["HERMES_HOME"] = str(ROOT)
            poisoned["PYTHONPATH"] = str(ROOT)
            poisoned["COMMANDCODE_API_KEY"] = "should-never-appear"
            poisoned["CORPUS_ROOT"] = str(ROOT / "corpus")
            raw_bytes = json.dumps(
                {"status": "ABSTAIN", "reason": "无法确认边界"},
                ensure_ascii=False,
            ).encode("utf-8")
            write_staged_raw(stage["output"], raw_bytes)
            before = sha256((stage["output"] / "raw.txt").read_bytes()).hexdigest()
            rec = launch_stage_child(
                staging_root=stage["root"],
                book_id="bookX",
                metric="B01",
                rep=1,
                run_id="isolation_unit",
                raw_file=stage["output"] / "raw.txt",
            )
            after = sha256((stage["output"] / "raw.txt").read_bytes()).hexdigest()
            self.assertEqual(before, after)
            self.assertEqual(rec.get("status"), "ABSTAIN")
            launch_meta = json.loads((stage["output"] / "child_launch.json").read_text(encoding="utf-8"))
            argv = " ".join(launch_meta.get("argv") or [])
            self.assertIn("--raw-file output/raw.txt", argv.replace("\\", "/"))
            self.assertIn("--staging-root .", argv)
            self.assertNotIn("api_key", argv.lower())
            self.assertNotIn(".env", argv.lower())
            self.assertTrue((stage["output"] / "provenance.json").is_file())
            self.assertTrue((stage["output"] / "result.json").is_file())
            # leftover: original PAYLOAD_ONLY check replaced by ABSTAIN lifecycle
            _ = rec.get("status") == "ABSTAIN"
            audit_p = stage["output"] / "child_audit.json"
            self.assertTrue(audit_p.is_file())
            audit = json.loads(audit_p.read_text(encoding="utf-8"))
            self.assertNotEqual(audit["pid"], os.getpid())
            self.assertEqual(Path(audit["cwd"]).resolve(), stage["root"].resolve())
            keys_u = {k.upper() for k in audit["env_keys"]}
            self.assertNotIn("HERMES_HOME", keys_u)
            self.assertNotIn("PYTHONPATH", keys_u)
            self.assertEqual(audit["forbidden_env_keys"], [])
            launch_meta = json.loads((stage["output"] / "child_launch.json").read_text(encoding="utf-8"))
            self.assertEqual(launch_meta["parent_pid"], os.getpid())
            blob = json.dumps(audit) + json.dumps(rec)
            self.assertNotIn("should-never-appear", blob)
            self.assertFalse((Path(td) / "cards").exists())
            # parent poison must not leak via sanitize
            cleaned = sanitize_child_env(poisoned)
            self.assertNotIn("HERMES_HOME", cleaned)
            self.assertNotIn("PYTHONPATH", cleaned)
            self.assertTrue(all(not env_key_forbidden(k) for k in cleaned))

    def test_malicious_paths_rejected_parent_and_child(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            stage = _make_stage(Path(td))
            with self.assertRaises(StageBoundaryError):
                validate_stage_bundle(
                    staging_root=stage["root"],
                    text=ROOT,
                    specs=stage["specs"],
                    config=stage["config"],
                    output=stage["output"],
                )
            with self.assertRaises(StageBoundaryError):
                validate_stage_bundle(
                    staging_root=stage["root"],
                    text=stage["text"],
                    specs=stage["specs"],
                    config=stage["config"],
                    output=ROOT / "scorer_v5" / "experiments" / "dev10" / "runs" / "dev10_v5_r3",
                )
            proc = subprocess.run(
                [
                    sys.executable,
                    str(STAGE_PY),
                    "--staging-root",
                    str(ROOT),
                    "--text",
                    str(ROOT / "corpus"),
                    "--specs",
                    str(SPECS_DIR),
                    "--config",
                    str(CONFIG_SRC),
                    "--output",
                    str(ROOT),
                    "--book-id",
                    "x",
                    "--metric",
                    "B01",
                    "--rep",
                    "1",
                    "--run-id",
                    "nope",
                    "--no-http",
                ],
                capture_output=True,
                text=True,
                cwd=str(stage["root"]),
                env=sanitize_child_env(),
            )
            self.assertEqual(proc.returncode, 2)

    def test_exception_classes_write_only_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            mapping = []

            def _run_transport(raw, label):
                stage = _make_stage(base / label)
                rec = execute_stage_card(
                    staging_root=stage["root"],
                    book_id="bookX",
                    metric="B01",
                    rep=1,
                    run_id="isolation_unit",
                    transport=lambda prompt, cfg: (raw, {"http_status": 0, "mock": True}),
                    allow_http=False,
                )
                results = list(stage["root"].rglob("result.json"))
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0].resolve(), (stage["output"] / "result.json").resolve())
                self.assertFalse((base / "cards").exists())
                mapping.append((label, rec.get("status"), rec.get("reason")))
                return rec

            parse_rec = _run_transport("{not-json", "parse")
            self.assertIn(parse_rec["status"], {"FAIL_PARSE", "BLOCKED", "SCHEMA_FAIL"})
            schema_rec = _run_transport('{"unexpected": true}', "schema")
            self.assertIn(schema_rec["status"], {"FAIL_SCHEMA", "SCHEMA_FAIL", "FAIL_PARSE", "BLOCKED"})
            abstain_rec = execute_stage_card(
                staging_root=_make_stage(base / "abstain_map")["root"],
                book_id="bookX",
                metric="B01",
                rep=1,
                run_id="isolation_unit",
                transport=None,
                allow_http=False,
            )
            self.assertEqual(abstain_rec["status"], "PAYLOAD_ONLY")
            self.assertEqual(
                classify_status({"abstained": True}),
                "ABSTAIN",
            )
            self.assertEqual(
                classify_status({"error": "EVIDENCE_FAIL", "validation": {"outcome": "EVIDENCE_FAIL"}}),
                "EVIDENCE_FAIL",
            )
            self.assertEqual(
                classify_status({"error": "LOGIC_FAIL", "validation": {"outcome": "LOGIC_FAIL"}}),
                "LOGIC_FAIL",
            )
            # preflight fail via missing specs yamls after bundle created: rewrite config provider
            stage_pf = _make_stage(base / "preflight")
            stage_pf["config"].write_text(
                "provider: commandcode\nmodel: deepseek/deepseek-v4-flash\ntemperature: 0.0\ntop_p: 1.0\nseed: 0\nmax_tokens: 8\n",
                encoding="utf-8",
            )
            write_staged_raw(stage_pf["output"], '{"status":"ABSTAIN","reason":"x"}')
            rec_pf = launch_stage_child(
                staging_root=stage_pf["root"],
                book_id="bookX",
                metric="B01",
                rep=1,
                run_id="isolation_unit",
                raw_file=stage_pf["output"] / "raw.txt",
            )
            self.assertEqual(rec_pf.get("status"), "BLOCKED")
            self.assertEqual(rec_pf.get("reason"), "preflight_failed")
            self.assertTrue((stage_pf["output"] / "result.json").is_file())
            # transport failure maps to confined BLOCKED
            stage_tr = _make_stage(base / "transport")

            def boom(prompt, cfg):
                raise RuntimeError("socket-forbidden")

            rec_tr = execute_stage_card(
                staging_root=stage_tr["root"],
                book_id="bookX",
                metric="B01",
                rep=1,
                run_id="isolation_unit",
                transport=boom,
                allow_http=False,
            )
            self.assertEqual(rec_tr["status"], "BLOCKED")
            self.assertEqual(rec_tr.get("reason"), "llm_call_failed")
            self.assertTrue((stage_tr["output"] / "result.json").is_file())
            self.assertEqual(list(base.rglob("cards")), [])

    def test_fan_in_readonly_sorted_dedup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            staging = base / "staging"
            cards = base / "cards"
            cards.mkdir()
            (cards / "should_not_read.json").write_text('{"status":"LEAK"}', encoding="utf-8")
            dest = base / "fan_in_tmp"

            def _put(book, metric, rep, status, extra=None):
                out = staging / book / metric / f"rep{rep}" / "output"
                out.mkdir(parents=True, exist_ok=True)
                rec = {
                    "book_id": book,
                    "metric_id": metric,
                    "rep": rep,
                    "status": status,
                    "score": None,
                }
                if extra:
                    rec.update(extra)
                (out / "result.json").write_text(json.dumps(rec), encoding="utf-8")
                (out / "provenance.json").write_text("{}", encoding="utf-8")

            _put("b2", "B02", 1, "OK")
            _put("b1", "B01", 2, "FAIL_PARSE")
            _put("b1", "B01", 1, "ABSTAIN")
            # duplicate identity: later glob order overwritten by last write into dict
            _put("b1", "B01", 1, "OK")
            summary = fan_in_staging_outputs(staging, dest_dir=dest)
            self.assertEqual(summary["written"], 3)
            self.assertEqual(summary["cards_read"], 0)
            self.assertEqual(summary["source"], "staging_output_readonly")
            self.assertEqual(summary["identities"], [["b1", "B01", 1], ["b1", "B01", 2], ["b2", "B02", 1]])
            lines = (dest / "fan_in_results.jsonl").read_text(encoding="utf-8").splitlines()
            ids = [json.loads(x)["id"] + json.loads(x)["metric_id"] + str(json.loads(x)["rep"]) for x in lines]
            self.assertEqual(ids, sorted(ids))
            self.assertEqual(json.loads(lines[0])["status"], "OK")
            self.assertFalse((cards / "written.json").exists())
            # scoring path must not call write_summaries: symbol exists but fan-in is separate
            src = (EXP / "run_dev10.py").read_text(encoding="utf-8")
            self.assertIn("fan_in_staging_outputs", src)
            self.assertIn("launch_stage_child", src)
            # after jobs, summaries come from fan-in not write_summaries
            self.assertIn("fan_in_staging_outputs(RUN_DIR / \"staging\"", src)

    def test_legacy_cards_do_not_satisfy_pending(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            _RUN.RUN_DIR = base / "runs" / "iso"
            book_id, metric, rep = "bookX", "B01", 1
            cards = _RUN.card_dir(book_id, metric, rep)
            cards.mkdir(parents=True)
            (cards / "result.json").write_text(
                json.dumps({"status": "OK", "score": 10}), encoding="utf-8"
            )
            self.assertFalse(_RUN.is_done(book_id, metric, rep))
            stage_out = _RUN.staging_dir(book_id, metric, rep) / "output"
            stage_out.mkdir(parents=True)
            (stage_out / "result.json").write_text(
                json.dumps({"status": "FAIL_PARSE"}), encoding="utf-8"
            )
            self.assertTrue(_RUN.is_done(book_id, metric, rep))

    def test_subprocess_raw_lifecycle_terminals(self) -> None:
        cases = [
            ("parse", "{not-json", {"FAIL_PARSE", "BLOCKED", "SCHEMA_FAIL"}),
            ("schema", '{"status":"OK","semantic":{}}', {"FAIL_SCHEMA", "SCHEMA_FAIL", "FAIL_PARSE", "BLOCKED"}),
            ("abstain", json.dumps({"status": "ABSTAIN", "reason": "无法确认边界"}, ensure_ascii=False), {"ABSTAIN"}),
            (
                "evidence",
                json.dumps(
                    {
                        "status": "OK",
                        "semantic": {
                            "candidates": [
                                {
                                    "event_quote": "这段文字绝不出现在正文XYZQQQ",
                                    "nearby_anchor": "nope",
                                    "is_external_event": True,
                                    "same_scene_action": False,
                                    "action_quote": None,
                                    "qualifies": True,
                                }
                            ],
                            "selection_note": "n",
                        },
                    },
                    ensure_ascii=False,
                ),
                {"EVIDENCE_FAIL", "LOGIC_FAIL", "FAIL_SCHEMA", "SCHEMA_FAIL", "FAIL_PARSE", "OK", "BLOCKED"},
            ),
        ]
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            for label, raw, allowed in cases:
                with self.subTest(label=label):
                    stage = _make_stage(base / label)
                    write_staged_raw(stage["output"], raw)
                    rec = launch_stage_child(
                        staging_root=stage["root"],
                        book_id="bookX",
                        metric="B01",
                        rep=1,
                        run_id="isolation_unit",
                        raw_file=stage["output"] / "raw.txt",
                    )
                    self.assertIn(rec.get("status"), allowed, msg=json.dumps(rec, ensure_ascii=False)[:400])
                    results = list(base.joinpath(label).rglob("result.json"))
                    self.assertEqual(len(results), 1)
                    self.assertEqual(results[0].resolve(), (stage["output"] / "result.json").resolve())
                    self.assertTrue((stage["output"] / "provenance.json").is_file() or rec.get("status") == "BLOCKED")
            # missing raw → BLOCKED missing_raw via real child
            stage_m = _make_stage(base / "missing")
            rec_m = launch_stage_child(
                staging_root=stage_m["root"],
                book_id="bookX",
                metric="B01",
                rep=1,
                run_id="isolation_unit",
            )
            self.assertEqual(rec_m.get("status"), "BLOCKED")
            self.assertEqual(rec_m.get("reason"), "missing_raw")
            # outside raw path rejected
            stage_b = _make_stage(base / "badraw")
            outsider = base / "outside.txt"
            outsider.write_text("x", encoding="utf-8")
            with self.assertRaises(StageBoundaryError):
                launch_stage_child(
                    staging_root=stage_b["root"],
                    book_id="bookX",
                    metric="B01",
                    rep=1,
                    run_id="isolation_unit",
                    raw_file=outsider,
                )
            src = (EXP / "run_dev10.py").read_text(encoding="utf-8")
            self.assertNotIn("result_path(book_id, metric, rep),", src)
            self.assertIn("parent_missing_raw", src)

    def test_process_card_ast_calls_write_staged_raw_and_acquire(self) -> None:
        tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
        fn = None
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "process_card":
                fn = node
                break
        self.assertIsNotNone(fn)
        names: list[str] = []
        for n in ast.walk(fn):
            if isinstance(n, ast.Call):
                if isinstance(n.func, ast.Name):
                    names.append(n.func.id)
                elif isinstance(n.func, ast.Attribute):
                    names.append(n.func.attr)
        self.assertIn("write_staged_raw", names)
        self.assertIn("launch_stage_child", names)
        src = ast.get_source_segment(RUNNER.read_text(encoding="utf-8"), fn) or ""
        self.assertIn("acquire", src)
        self.assertNotIn("call_minimax", names)
        write_src = (EXP / "stage_only_exec.py").read_text(encoding="utf-8")
        self.assertIn("os.replace", write_src)
        self.assertIn("mkstemp", write_src)

    def test_parent_injected_transport_atomic_raw_handoff(self) -> None:
        calls: list[bytes] = []
        real_write = _mod.write_staged_raw

        def tracing_write(output, raw):
            data = raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
            calls.append(data)
            return real_write(output, raw)

        _RUN.write_staged_raw = tracing_write
        try:
            with tempfile.TemporaryDirectory() as td:
                base = Path(td)
                book = {"id": "bookX"}

                def prepare(book, metric, rep):
                    del book, metric, rep
                    return _make_stage(base / "ok")

                payload = json.dumps(
                    {"status": "ABSTAIN", "reason": "无法确认边界"},
                    ensure_ascii=False,
                ).encode("utf-8")
                want_hash = sha256(payload).hexdigest()

                def acquire_ok(*, book, metric, rep, stage):
                    del book, metric, rep, stage
                    return payload

                rec = _RUN.process_card(
                    book=book,
                    metric="B01",
                    rep=1,
                    cfg={},
                    api_key="must-not-read",
                    base_url="http://must-not-call",
                    model_params={},
                    acquire_parent_raw=acquire_ok,
                    prepare_fn=prepare,
                )
                self.assertEqual(rec.get("status"), "ABSTAIN")
                self.assertEqual(len(calls), 1)
                self.assertEqual(sha256(calls[0]).hexdigest(), want_hash)
                raw_p = base / "ok" / "runs" / "isolation_unit" / "staging" / "bookX" / "B01" / "rep1" / "output" / "raw.txt"
                self.assertEqual(sha256(raw_p.read_bytes()).hexdigest(), want_hash)
                self.assertFalse(list(raw_p.parent.glob(".raw.*.tmp")))

                def prepare_miss(book, metric, rep):
                    del book, metric, rep
                    return _make_stage(base / "miss")

                rec_m = _RUN.process_card(
                    book=book,
                    metric="B01",
                    rep=1,
                    cfg={},
                    api_key="",
                    base_url="",
                    model_params={},
                    acquire_parent_raw=lambda **k: None,
                    prepare_fn=prepare_miss,
                )
                self.assertEqual(rec_m.get("status"), "BLOCKED")
                self.assertEqual(rec_m.get("reason"), "parent_missing_raw")
                miss_out = base / "miss" / "runs" / "isolation_unit" / "staging" / "bookX" / "B01" / "rep1" / "output"
                self.assertTrue((miss_out / "result.json").is_file())
                self.assertFalse((miss_out / "raw.txt").is_file())

                def prepare_fail(book, metric, rep):
                    del book, metric, rep
                    return _make_stage(base / "fail")

                def acquire_fail(**_k):
                    raise _RUN.ParentTransportError("injected fail")

                rec_f = _RUN.process_card(
                    book=book,
                    metric="B01",
                    rep=1,
                    cfg={},
                    api_key="",
                    base_url="",
                    model_params={},
                    acquire_parent_raw=acquire_fail,
                    prepare_fn=prepare_fail,
                )
                self.assertEqual(rec_f.get("status"), "BLOCKED")
                self.assertEqual(rec_f.get("reason"), "parent_transport_failed")
                fail_out = base / "fail" / "runs" / "isolation_unit" / "staging" / "bookX" / "B01" / "rep1" / "output"
                self.assertTrue((fail_out / "result.json").is_file())
        finally:
            _RUN.write_staged_raw = real_write

    def test_write_staged_raw_atomic_replace_hash(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "output"
            out.mkdir()
            data = b"raw-bytes-\xe6\x88\x91"
            dest = write_staged_raw(out, data)
            self.assertEqual(dest.read_bytes(), data)
            self.assertEqual(sha256(dest.read_bytes()).hexdigest(), sha256(data).hexdigest())
            leftovers = list(out.glob(".raw.*.tmp"))
            self.assertEqual(leftovers, [])
            dest2 = write_staged_raw(out, b"second")
            self.assertEqual(dest2.read_bytes(), b"second")


def main() -> int:
    # Refuse touching frozen run mtimes via this test file.
    before = {p: _sha256_file(p / "summary.json") for p in FROZEN_RUNS if (p / "summary.json").is_file()}
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(IsolationTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    after = {p: _sha256_file(p / "summary.json") for p in FROZEN_RUNS if (p / "summary.json").is_file()}
    if before != after:
        print("FAIL: frozen summary hashes changed", file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())

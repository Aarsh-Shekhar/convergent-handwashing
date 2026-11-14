"""Command-line entry point: ``python -m convergent.cli <command>`` or ``convergent <command>``.

Commands
--------
replay        run the integrated pipeline on a prerecorded video (deterministic)
camera        run the pipeline on a local webcam
network       run the pipeline on frames streamed by the Pi agent / emulator (starts the gateway)
backend       start the FastAPI backend (applies migrations)
pi-emulator   run the Pi agent locally with an emulated camera + image renderer
pi-agent      run the real Pi agent (on the Raspberry Pi)
calibrate     projector calibration: synthetic self-test, pattern generation, from correspondences
evaluate      model evaluation (delegates to scripts/evaluate_models.py)
models        print artifact discovery/availability
test          run the test-suite (pytest)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from convergent.common.config import PipelineConfig, load_settings, repo_root, resolve_path
from convergent.common.logging import configure_logging, get_logger

log = get_logger("convergent.cli")


def _config(args: argparse.Namespace, overrides: dict[str, Any]) -> PipelineConfig:
    path = resolve_path(args.config) if args.config else resolve_path("configs/development.yaml")
    return PipelineConfig.load(path if path.exists() else None, overrides)


def _backend_client(args: argparse.Namespace, cfg: PipelineConfig):  # type: ignore[no-untyped-def]
    from convergent.backend.client import BackendClient, inprocess_client

    settings = load_settings()
    mode = getattr(args, "backend", "none")
    if mode == "none":
        return None
    if mode == "inprocess":
        client, _app = inprocess_client(settings.api_token or "dev-inprocess-token", settings.database_url)
        return client
    if not settings.api_token:
        raise SystemExit("CONVERGENT_API_TOKEN must be set to write to the backend (see .env.example)")
    client = BackendClient(cfg.backend.base_url if mode == "http" else mode, settings.api_token, cfg.backend.timeout_s)
    client.health()
    return client


def _print_summary(summary) -> None:  # type: ignore[no-untyped-def]
    print(f"\nsession {summary.session_id}  source={summary.source_id}  frames={summary.frames}  wall={summary.duration_s:.1f}s")
    print(f"fused statuses: {summary.fused_counts}   latency p50={summary.latency['p50_ms']:.1f}ms p90={summary.latency['p90_ms']:.1f}ms")
    for k, v in summary.model_status.items():
        print(f"  model {k:<14} available={v['available']!s:<5} {v['message']}")
    print(f"validated events: {len(summary.events)}")
    for e in summary.events:
        print(f"  {e.start_ts:7.2f}-{e.end_ts:7.2f}s {e.technique:<20} side={e.side.value:<10} dur={e.validated_duration_s:.2f}s conf={e.confidence:.2f} resolved={e.side_resolved}")
    if summary.progress:
        print(f"coverage_estimate={summary.progress['coverage_estimate']:.2f} (observed-evidence estimate, not cleanliness)")
    sc = getattr(summary, "score", None)
    if sc:
        status = f"FINISHED at {sc['finished_at_ts']:.1f}s" if sc["finished"] else "not finished"
        print(f"wash score: {sc['stars']}/5 stars, {sc['points']} points, {status}")
        print(f"  steps done {sc['steps_done']}/{sc['steps_required']} needed (each {sc['step_min_s']:.0f}s), "
              f"total {sc['total_s']:.1f}s of {sc['total_min_s']:.0f}s needed")
        for st in sc["steps"]:
            print(f"  [{'x' if st['done'] else ' '}] {st['technique']:<20} {st['seconds']:5.1f}s")
        if not sc["finished"] and sc["next_step"]:
            print(f"  next suggested step: {sc['next_step']}")
        print("  (score = recognized washing-motion time, not proof of clean hands)")
    soap = (summary.progress or {}).get("procedure_states", {}).get("soap")
    if soap:
        print(f"soap/lather seen: {'yes' if soap in ('seen', 'detected') else 'no'}  (unvalidated brightness heuristic, UI only)")
    if summary.results_dir:
        print(f"results: {summary.results_dir}")
    if summary.backend:
        print(f"backend: {summary.backend}")


# --------------------------------------------------------------------------- commands
def cmd_replay(args: argparse.Namespace) -> int:
    from convergent.pipeline import Pipeline

    cfg = _config(args, {"source": {"kind": "video", "path": args.video, "max_frames": args.max_frames, "target_fps": args.fps},
                         "results_dir": args.results_dir})
    client = _backend_client(args, cfg)
    pipe = Pipeline(cfg, backend_client=client, deterministic=True, save_results=args.save_results)
    try:
        summary = pipe.run()
    finally:
        pipe.close()
    _print_summary(summary)
    if args.json:
        Path(args.json).write_text(summary.to_json(), encoding="utf-8")
    return 0


def cmd_camera(args: argparse.Namespace) -> int:
    from convergent.pipeline import Pipeline

    cfg = _config(args, {"source": {"kind": "webcam", "device_index": args.device, "max_frames": args.max_frames, "target_fps": args.fps},
                         "results_dir": args.results_dir})
    client = _backend_client(args, cfg)
    pipe = Pipeline(cfg, backend_client=client, deterministic=False, save_results=args.save_results)
    if args.show:
        import cv2

        from convergent.vision.overlays import draw_score_panel, render_overlay

        def _show(r):  # type: ignore[no-untyped-def]
            pass

        pipe.on_frame = _show  # overlay needs the image; use the source frame directly
        orig = pipe.process_frame

        def _proc(frame):  # type: ignore[no-untyped-def]
            r = orig(frame)
            img = render_overlay(frame, r.hands, [f"fused={r.fused.native_label or r.fused.status.value} conf={r.fused.confidence}",
                                                  "Esc = stop and print score"])
            if r.score is not None:
                draw_score_panel(img, r.score, soap=r.soap)
            cv2.imshow("convergent diagnostics", img)
            if cv2.waitKey(1) & 0xFF == 27:
                pipe.stop()  # normal end: summary, score and session end are saved
            return r

        pipe.process_frame = _proc  # type: ignore[method-assign]
    try:
        summary = pipe.run()
    except KeyboardInterrupt:  # Ctrl+C outside the frame loop (e.g. while models load)
        summary = None
    finally:
        pipe.close()
    if summary:
        _print_summary(summary)
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    from convergent.vision.recorder import RECORD_CLASSES, record_round

    round_id = args.round or time.strftime("r%Y%m%d_%H%M%S")
    classes = [c.strip() for c in args.classes.split(",")] if args.classes else list(RECORD_CLASSES)
    print(f"recording round {round_id!r} (view={args.view}): {len(classes)} clips of {args.seconds:.0f}s. Esc stops.")
    rdir = record_round(resolve_path(args.out), round_id, device=args.device, view=args.view, seconds=args.seconds,
                        ready_s=args.ready, fps=args.fps, classes=classes)
    done = sorted(p.stem for p in rdir.glob("*.mp4"))
    print(f"round saved to {rdir} ({len(done)}/{len(classes)} clips: {', '.join(done)})")
    return 0


def cmd_network(args: argparse.Namespace) -> int:
    from convergent.communication.websocket import DeviceGateway
    from convergent.pipeline import Pipeline
    from convergent.vision.sources import NetworkSource

    cfg = _config(args, {"source": {"kind": "network", "max_frames": args.max_frames, "target_fps": args.fps}, "results_dir": args.results_dir})
    settings = load_settings()
    source = NetworkSource(cfg.source, queue_size=cfg.queue_size, read_timeout_s=args.timeout)
    gateway = DeviceGateway(source, args.host, args.port, token=os.environ.get("CONVERGENT_DEVICE_TOKEN", settings.api_token),
                            config_for_device={"target_fps": cfg.source.target_fps, "width": cfg.source.width, "height": cfg.source.height, "jpeg_quality": 80})
    gateway.start()
    print(f"device gateway listening on ws://{args.host}:{gateway.port}  (waiting up to {args.timeout}s per frame)")
    client = _backend_client(args, cfg)
    pipe = Pipeline(cfg, source=source, backend_client=client, gateway=gateway, deterministic=False, save_results=args.save_results)
    try:
        summary = pipe.run()
    finally:
        pipe.close()
        gateway.stop()
    _print_summary(summary)
    print(f"device: {json.dumps(gateway.state.as_dict(), default=str)}")
    return 0


def cmd_backend(args: argparse.Namespace) -> int:
    from convergent.backend.app import run

    run(args.host, args.port, args.reload)
    return 0


def cmd_pi_emulator(args: argparse.Namespace) -> int:
    from convergent.pi_agent.agent import AgentConfig, PiAgent

    cfg = AgentConfig(laptop_url=args.url, device_id=args.device_id, camera="emulated", video_path=args.video, renderer="image",
                      render_out_dir=args.render_out, fps=args.fps, max_frames=args.max_frames,
                      token=os.environ.get("CONVERGENT_DEVICE_TOKEN", load_settings().api_token))
    agent = PiAgent(cfg)
    agent.run()
    print(f"emulator stats: {agent.transport.stats}")
    return 0


def cmd_pi_agent(args: argparse.Namespace) -> int:
    from convergent.pi_agent.__main__ import main as agent_main

    return agent_main(args.agent_args)


def cmd_calibrate(args: argparse.Namespace) -> int:
    sys.argv = ["calibrate_projector.py", *args.cal_args]
    script = repo_root() / "scripts" / "calibrate_projector.py"
    return subprocess.call([sys.executable, str(script), *args.cal_args])


def cmd_evaluate(args: argparse.Namespace) -> int:
    script = repo_root() / "scripts" / "evaluate_models.py"
    return subprocess.call([sys.executable, str(script), *args.eval_args])


def cmd_models(args: argparse.Namespace) -> int:
    from convergent.detection.registry import ModelRegistry
    from convergent.pipeline import Pipeline

    cfg = _config(args, {})
    print("Artifact discovery (configs/models.yaml):")
    for d in ModelRegistry.load(cfg.models_registry_path).discover_all():
        print(f"  {d['model_key']:<28} exists={d['exists']!s:<5} trusted={d['trusted']!s:<5} {d['path']}")
    print("\nAdapter load status:")
    pipe = Pipeline(cfg.model_copy(update={"tracker": cfg.tracker.model_copy(update={"backend": "null"})}), deterministic=True)
    for k, st in pipe.load_models().items():
        print(f"  {k:<14} available={st.available!s:<5} version={st.version:<28} {st.message}")
    return 0


def cmd_test(args: argparse.Namespace) -> int:
    cmd = [sys.executable, "-m", "pytest", *args.pytest_args]
    return subprocess.call(cmd, cwd=repo_root())


# --------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="convergent", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=None, help="pipeline YAML (default configs/development.yaml)")
    ap.add_argument("--log-level", default=None)
    sub = ap.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--backend", default="none", help="none | inprocess | http | ws://... (http uses configs backend.base_url)")
        p.add_argument("--save-results", action="store_true")
        p.add_argument("--results-dir", default="runs")
        p.add_argument("--max-frames", type=int, default=None)
        p.add_argument("--fps", type=float, default=15.0)

    p = sub.add_parser("replay", help="run the pipeline on a prerecorded video")
    p.add_argument("--video", required=True)
    p.add_argument("--json", default=None, help="write the run summary JSON here")
    common(p)
    p.set_defaults(func=cmd_replay)

    p = sub.add_parser("camera", help="run the pipeline on a local webcam")
    p.add_argument("--device", type=int, default=0)
    p.add_argument("--show", action="store_true", help="show the diagnostic overlay window")
    common(p)
    p.set_defaults(func=cmd_camera)

    p = sub.add_parser("record", help="record labelled washing clips from the webcam (one clip per step)")
    p.add_argument("--device", type=int, default=0)
    p.add_argument("--view", default="down", help="free-text camera view tag, e.g. down | front")
    p.add_argument("--round", default=None, help="round name (default: timestamp)")
    p.add_argument("--seconds", type=float, default=15.0, help="seconds recorded per step")
    p.add_argument("--ready", type=float, default=5.0, help="get-ready countdown before each step")
    p.add_argument("--fps", type=float, default=15.0)
    p.add_argument("--classes", default=None, help="comma-separated subset to (re)record")
    p.add_argument("--out", default="data/own")
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("network", help="run the pipeline on the Pi stream (starts the device gateway)")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--timeout", type=float, default=10.0, help="seconds to wait for a frame before ending the session")
    common(p)
    p.set_defaults(func=cmd_network)

    p = sub.add_parser("backend", help="start the FastAPI backend")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--reload", action="store_true")
    p.set_defaults(func=cmd_backend)

    p = sub.add_parser("pi-emulator", help="run a simulated Pi agent on this machine")
    p.add_argument("--url", default="ws://127.0.0.1:8765")
    p.add_argument("--device-id", default="pi-emulator")
    p.add_argument("--video", default=None)
    p.add_argument("--render-out", default="runs/pi_emulator_renders")
    p.add_argument("--fps", type=float, default=15.0)
    p.add_argument("--max-frames", type=int, default=None)
    p.set_defaults(func=cmd_pi_emulator)

    p = sub.add_parser("pi-agent", help="run the real Pi agent (pass agent args after --)")
    p.add_argument("agent_args", nargs=argparse.REMAINDER)
    p.set_defaults(func=cmd_pi_agent)

    p = sub.add_parser("calibrate", help="projector calibration tools (see scripts/calibrate_projector.py --help)")
    p.add_argument("cal_args", nargs=argparse.REMAINDER)
    p.set_defaults(func=cmd_calibrate)

    p = sub.add_parser("evaluate", help="model evaluation (see scripts/evaluate_models.py --help)")
    p.add_argument("eval_args", nargs=argparse.REMAINDER)
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("models", help="artifact discovery and adapter status")
    p.set_defaults(func=cmd_models)

    p = sub.add_parser("test", help="run the test-suite")
    p.add_argument("pytest_args", nargs=argparse.REMAINDER)
    p.set_defaults(func=cmd_test)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    configure_logging(args.log_level or settings.log_level, settings.log_dir, "convergent", settings.log_max_bytes, settings.log_backup_count)
    if args.command == "calibrate":
        args.cal_args = [a for a in args.cal_args if a != "--"]
    if args.command == "evaluate":
        args.eval_args = [a for a in args.eval_args if a != "--"]
    if args.command == "pi-agent":
        args.agent_args = [a for a in args.agent_args if a != "--"]
    if args.command == "test":
        args.pytest_args = [a for a in args.pytest_args if a != "--"]
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())

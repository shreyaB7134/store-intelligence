"""
CLI entry point for the detection pipeline.
Usage: python -m pipeline.run_pipeline --help
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Store Intelligence Detection Pipeline",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--video-path", required=True, help="Path to video file")
    parser.add_argument("--store-id", default="ST1008", help="Store identifier")
    parser.add_argument("--camera-id", default="CAM_1", help="Camera identifier")
    parser.add_argument("--layout", default=None, help="Path to store_layout.json")
    parser.add_argument("--api-url", default="http://localhost:8000", help="Intelligence API URL")
    parser.add_argument("--max-fps", type=float, default=10.0, help="Processing FPS limit")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args()


async def main():
    args = parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    video_path = Path(args.video_path)
    if not video_path.exists():
        logger.error("Video file not found: %s", video_path)
        sys.exit(1)

    from pipeline.video_processor import VideoProcessor

    processor = VideoProcessor(
        store_id=args.store_id,
        camera_id=args.camera_id,
        layout_path=args.layout,
        api_url=args.api_url,
        max_fps=args.max_fps,
    )

    logger.info("Starting pipeline for %s / %s", args.store_id, args.camera_id)
    stats = await processor.process_video(str(video_path))

    print("\n=== Pipeline Complete ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())

"""下载公开样本或运行一次真实 API 分析；结果保存在被忽略的目录。"""

import argparse
import io
import json
import sys

import httpx
from PIL import Image

from .vision import (
    DATA_DIR,
    MAX_BYTES,
    SAMPLE_DIR,
    VisionError,
    analyze_sample,
    prepare_image,
    samples,
)


def download():
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        for sample in samples():
            path = SAMPLE_DIR / (sample["id"] + ".jpg")
            if path.is_file():
                print(sample["id"], "already present")
                continue
            if sample["url"]:
                content = bytearray()
                with client.stream("GET", sample["url"]) as response:
                    response.raise_for_status()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > MAX_BYTES:
                            raise VisionError("下载文件超过大小限制", 422)
                content = bytes(content)
            else:
                buffer = io.BytesIO()
                Image.new("RGB", (512, 512), (180, 180, 180)).save(buffer, "PNG")
                content = buffer.getvalue()
            path.write_bytes(prepare_image(content))
            print(sample["id"], "downloaded")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["download", "analyze"])
    parser.add_argument("--image", choices=[sample["id"] for sample in samples()])
    parser.add_argument("--allow-remote-upload", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "download":
            download()
        else:
            if not args.allow_remote_upload:
                parser.error("远程分析需指定 --allow-remote-upload")
            results = []
            for sample in samples():
                if args.image and sample["id"] != args.image:
                    continue
                result = analyze_sample(sample["id"])
                results.append(result)
                print(json.dumps(result, ensure_ascii=False))
            directory = DATA_DIR
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "deepseek-image-report.json").write_text(
                json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    except (VisionError, httpx.HTTPError) as exc:
        print(
            str(exc)
            if isinstance(exc, VisionError)
            else "公开样本下载失败，请检查网络",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

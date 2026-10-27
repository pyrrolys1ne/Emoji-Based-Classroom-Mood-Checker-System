from fastapi import HTTPException


def pending(feature: str):
    """框架统一显式拒绝未实现操作，避免返回虚假的成功。"""
    raise HTTPException(501, f"{feature}尚未实现；当前版本为项目框架。")

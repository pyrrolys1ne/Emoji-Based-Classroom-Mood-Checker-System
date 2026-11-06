import argparse
import getpass
import sys
import warnings


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, "命令参数无效，请使用 --help 查看用法。\n")


class InputError(ValueError):
    pass


def read_password(from_stdin: bool, *, confirm: bool = False) -> str:
    if from_stdin:
        password = sys.stdin.read(1025).removesuffix("\n").removesuffix("\r")
        if "\n" in password or "\r" in password:
            raise InputError("标准输入必须只包含一行密码。")
        return password
    if not sys.stdin.isatty():
        raise InputError("交互输入需要终端；自动化环境请显式使用 --password-stdin。")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("管理员密码：")
            if confirm and password != getpass.getpass("再次输入密码："):
                raise InputError("两次密码输入不一致。")
    except getpass.GetPassWarning:
        raise InputError("当前终端不能隐藏密码，请使用安全标准输入方式。") from None
    return password

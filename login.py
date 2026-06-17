"""BJTU 校园网登录"""

import argparse
import requests


def main():
    parser = argparse.ArgumentParser(description="BJTU 校园网登录")
    parser.add_argument("-u", "--username", required=True, help="学号")
    parser.add_argument("-p", "--password", required=True, help="密码")
    args = parser.parse_args()

    r = requests.get(
        "https://login.bjtu.edu.cn:802/eportal/portal/login",
        params={
            "user_account": args.username,
            "user_password": args.password,
        },
    )
    print(r.text)


if __name__ == "__main__":
    main()

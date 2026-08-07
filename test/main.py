"""MVP 游戏入口。

启动: cd test && python main.py
"""

from render.textual.app import MVPApp


def main():
    app = MVPApp()
    app.run()


if __name__ == "__main__":
    main()

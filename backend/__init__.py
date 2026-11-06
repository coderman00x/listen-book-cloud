"""听书宝（listen_book）后端包。

所有磁盘读写都集中在 app 自身的 ``data/`` 目录下，
绝不触碰用户原始 txt 文件的绝对路径（见 docs/ARCHITECTURE.md 原始文件红线）。
"""

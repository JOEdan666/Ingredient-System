# T01 InvenTree 实测证据

运行日期：2026-09-27 · 运行者：Claude Code · 平台：macOS 26.6.2 arm64，Python 3.13.5
被测版本：InvenTree `1.5.6`（GitHub tag，2026-09-26 发布，MIT）· 数据库：SQLite · 数据：全部为合成数据

## 运行范围

- 只运行了**后端**：没有启动网页界面，也没有开 HTTP 端口。脚本在 `manage.py shell` 里直接调用 InvenTree 的模型和分配接口序列化器 `SalesOrderShipmentAllocationSerializer`，与网页"分配库存"按钮走的是同一条校验路径（`order/serializers.py`）。
- 本机缺少 WeasyPrint 需要的 pango 库，所以用一个空壳模块代替了 `weasyprint`。**标签、报表和 PDF 都没有验证。**
- 用的是 SQLite。**并发加锁没有实测**；A06 只测了"顺序提交两次"的情况，并发保护的结论来自源码（`lock_quantity()`，内部是 `select_for_update`）。

## 复现

```sh
curl -sL https://github.com/inventree/InvenTree/archive/refs/tags/1.5.6.tar.gz | tar xz
python3 -m venv venv && . venv/bin/activate
pip install -r InvenTree-1.5.6/src/backend/requirements.txt
export INVENTREE_DB_ENGINE=sqlite3 INVENTREE_DB_NAME=$PWD/db.sqlite3 \
  INVENTREE_MEDIA_ROOT=$PWD/media INVENTREE_STATIC_ROOT=$PWD/static \
  INVENTREE_BACKUP_DIR=$PWD/backup INVENTREE_CONFIG_FILE=$PWD/config.yaml \
  INVENTREE_SECRET_KEY=local-eval INVENTREE_SITE_URL=http://localhost:8000 \
  INVENTREE_PLUGINS_ENABLED=False
# 没有 pango 时：PYTHONPATH 指向一个只定义 HTML/CSS/urls.URLFetcher 的空壳 weasyprint 包
cd InvenTree-1.5.6/src/backend/InvenTree
python manage.py migrate --noinput          # 本次：761 个迁移 OK
python manage.py shell < scenarios.py       # 输出见 scenarios.out.txt
python manage.py shell < scenarios2.py      # 需要和 scenarios.py 在同一目录；输出见 scenarios2.out.txt
```

## 文件

- `scenarios.py` / `scenarios.out.txt`：A01 A02 A03 A04 A05 A06 A10 的场景和逐条结果。
- `scenarios2.py` / `scenarios2.out.txt`：重复提交同一个分配请求；发货后的库存历史里记录了哪些字段。

A03 和 A05 在 `scenarios.py` 里有几条只是检查"有没有这个字段"，结果标为 NO 的，意思是**没有这个字段**，并不代表运行出错。A05 的实际重复提交结果以 `scenarios2.out.txt` 为准。

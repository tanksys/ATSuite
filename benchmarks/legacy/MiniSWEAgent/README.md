# Mini-SWE-Agent

[Modified Url](https://gitee.com/lpzhao-tju/mini-swe-agent)

## 提取 DAG

```bash
$ pip install -e .
$ mini-extra swebench-single --subset verified --split test -i 132 --model dashscope/qwen3-235b-a22b-thinking-2507 -d trace-test-132.json --no-cost-tracking
```

## Notes

原始的执行过程：

1. 首先通过默认配置 `config/extra/swebench.yaml` 加载对应 case 的 docker 镜像
2. 启动时：`_start_container()` 用 `docker run -d ... sleep 2h`` 起一个容器，记下 container_id。
3. 每次 `execute()`：用 `docker exec` 在同一个容器里跑 `bash -lc <command>`。
  - 同一个 run 里的多次 execute 都进同一个容器；
  - 容器内文件、已安装的包、写过的文件都会保留，步骤之间是有状态的。
4. 每次 `mini-extra swebench-single` 都会起新容器，跑完会清理，不复用。

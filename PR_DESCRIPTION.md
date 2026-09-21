# PR 标题（复制到 Title 框）

refactor: 拆分 agent/nodes.py 单体为 16 个职责模块

---

# PR 描述（复制到描述框）

## 概要

`agent/nodes.py` 早期把全部 Agent 逻辑写在一个文件里（4391 行 / 255 个函数），这是面试官打开仓库的第一印象，本 PR 按职责把它拆成 16 个模块。

## 方法

1. AST 建调用图，先搬**纯叶子函数**（无内部依赖，不可能循环导入）
2. 对语义组算**传递闭包**，闭包外依赖为 0 才整组搬迁
3. 新模块 import 从 nodes.py 原有 import 自动推导，ruff --fix 清理冗余
4. 每步搬迁后静态校验无未定义名字引用，52 个测试必须全绿才 commit

## 前后对比（真实运行得出）

| 指标 | 前 | 后 |
| --- | --- | --- |
| nodes.py 行数 | 4391 | **852（-81%）** |
| agent/ 模块数 | 5 | **16** |
| 覆盖率（总体） | 74% | 75% |
| 覆盖率（nodes.py） | 79% | 83% |
| 测试 | 52 绿 | 52 绿（全程未红） |
| lint | 无 | ruff 通过（E4/E7/E9/F/I/UP） |

## 顺带补齐

- MIT LICENSE
- CI 接入 ruff
- README 增加重构对比表与 badge，前端本地路径改为公开仓库链接
- 测试打桩目标随实现迁移（patch 必须指向函数新定义模块，且覆盖全部调用点）

## 验证

```bash
python -m unittest discover -s tests   # 52 通过
ruff check .                           # 通过
uvicorn api:app                        # POST /app/plan 冒烟正常
```

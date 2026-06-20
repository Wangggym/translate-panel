# translate-panel 开发规范

> 完整开发规范见 [AGENTS.md](./AGENTS.md)，核心要求：**写完代码必须自测，能自主闭环，交付可靠版本**。

## 快速参考

### 改代码后如何生效

代码通过软链指向 repo，无需重装，只需重启 daemon：

```bash
pkill -f daemon.py   # launchd 自动重启
```

### 回归测试

```bash
python3 test_audio.py
```

### 日志

```bash
tail -f ~/.local/share/translate-panel/daemon.log
```

### 目录结构

```
app/
  daemon.py     ← 主进程（WKWebView + socket server）
  trigger.py    ← PopClip 触发脚本
popclip/        ← PopClip 插件
install.sh      ← 安装脚本（创建软链 + launchd plist）
test_audio.py   ← 快速回归入口
tests/cases/    ← E2E 用例，含场景描述和已知陷阱
```

# Case 001: 音频生命周期（播放 → 隐藏停止 → 再显示可播放）

## 场景

用户用 PopClip 触发翻译，在面板中点击 🔊 播放 TTS 音频，然后点击其他应用切走。  
预期：音频立即停止，面板隐藏。  
再次触发翻译，面板出现，音频功能正常，可以再次播放。

## 用户行为链

```
PopClip 选词 → 面板出现 → 点 🔊（音频播放）→ 点其他 App
    → 音频停止 + 面板隐藏
    → 再 PopClip 另一个词 → 面板出现 → 点 🔊（音频正常播放）
```

## 自动化运行

```bash
# 确保 daemon 已启动（launchd 管理）
cd translate-panel
python3 tests/cases/001-audio-flow/test_audio_flow.py
```

或直接用项目根部的快捷入口：

```bash
python3 test_audio.py
```

## 验证点

| 步骤 | 可观测事实 | 验证方式 |
|------|-----------|---------|
| 点 🔊 按钮 | JS click 返回 "Stop listening"（按钮状态变化）| eval JS |
| 切走 App | log: `pause_audio: clicked-stop` 或 `paused-dom: N` | 读日志 |
| 窗口隐藏 | log: `on_resign_key: window hidden` | 读日志 |
| 再显示 | log: `handle_client: window shown` | 读日志 |
| 再点 🔊 | JS click 返回 "Stop listening"（按钮再次变化）| eval JS |
| **音频是否真的有声音** | ⚠ 无法自动化，需人工确认 | 用耳朵听 |

## 已知陷阱（调试过程踩过的坑）

### 1. `pauseAllMediaPlaybackWithCompletionHandler_` 会永久 block 未来播放

**现象**：第一次音频正常 + 能停，第二次显示窗口后点 🔊 无声。  
**原因**：Apple 文档明确说 `pauseAllMediaPlayback` 调用后，后续播放被 block，直到显式调用 `setAllMediaPlaybackSuspended(false)`。  
**错误修法**：加 `resume_media()` 调用 `setAllMediaPlaybackSuspended(false)`。  
**为什么没用**：`setAllMediaPlaybackSuspended` 需要在 main thread 调用。从 background thread（handle_client 线程）调用时，completion handler 触发（看起来成功），但实际状态并未改变。  
**正确修法**：完全不用 `pauseAllMediaPlaybackWithCompletionHandler_`。改为注入 JS 直接点 Google Translate 的 "Stop listening" 按钮，让 GT 自己管理 AudioContext 状态。

### 2. `result=1.0` 不等于音频被停止

**现象**：旧 JS 方案 `querySelectorAll('audio,video')` 返回 1，以为停了音频。  
**原因**：返回值 1 来自 `speechSynthesis.cancel()` 的计数，不是真正找到了 audio 元素。  
Google Translate TTS 使用后端 TTS API + AudioContext（不是 DOM `<audio>` 元素），`querySelectorAll` 根本找不到。  
**教训**：测试返回值要理解含义，`audioCount: 0` 证实了 GT 不用 DOM audio。

### 3. 日志每行出现两次

**现象**：所有日志重复一遍。  
**原因**：Python `logging.StreamHandler` 把日志写到 stderr，launchd plist 的 `StandardErrorPath` 把 stderr 重定向到同一个 `daemon.log`，FileHandler 也在写同一个文件。  
**修法**：移除 Python `StreamHandler`，只保留 `FileHandler`。

### 4. NSObject 子类不能在函数内重复定义

**现象**：`objc.error: _Block is overriding existing Objective-C class`  
**原因**：在函数内定义 `class _Block(NSObject)` 每次调用都试图创建同名 ObjC class，ObjC class 注册是全局的，不能重复。  
**修法**：ObjC 子类必须在模块级定义，或确保只定义一次。

### 5. 测试脚本验证点过时导致误报

**现象**：代码已改但测试仍报 fail。  
**原因**：测试检查的日志字符串是旧版本的（如 `"pause_audio: native pauseAllMediaPlayback done"`），新版本日志字符串不同。  
**教训**：改代码同时必须更新对应测试的验证点，两者要一起维护。

## 架构说明

```
GT TTS 音频机制：
  用户点 🔊 → GT JS 代码 → 后端 TTS API → AudioContext 播放
  （不是 <audio> 元素，无法用 querySelectorAll 找到）

停止音频的正确方式：
  注入 JS → 找到 aria-label 含 "Stop" 的按钮 → click()
  → GT 自己调用 audioContext.suspend() 或 stop()
  → 不破坏 GT 内部状态机 → 下次点 🔊 正常工作
```

## 关键代码位置

- 停止音频 JS：`app/daemon.py` → `STOP_AUDIO_JS`
- 失焦回调：`app/daemon.py` → `on_resign_key()`
- socket eval 命令：`app/daemon.py` → `handle_client()` → `action == "eval"`
- 自动化测试脚本：`test_audio.py`（项目根）或本目录 `test_audio_flow.py`

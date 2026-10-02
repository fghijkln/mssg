# 在手机上运行 mssg（Android + Termux）

Hugo 是纯桌面 CLI 工具，手机上跑不起来。mssg 体积小（基础安装约 2.3MB，
纯 Python 依赖）+ 自带网页后台 `mssg admin`，在 Android 手机上就能完成
"写文章 → 构建 → 发布"全流程。

> 本文基于 mssg v0.9.0。云电脑上无法实测 Termux，
> 步骤按各环节已验证的事实拼装，欢迎在真机上验证后提 issue。

## 准备：安装 Termux

1. 去 **F-Droid** 下载 Termux（https://f-droid.org/packages/com.termux/）。
   不要用 Play 商店的版本——那个 2020 年就停更了。
2. 打开 Termux，执行：
   ```bash
   pkg update && pkg install python git
   ```
3. （可选）让 Termux 能读写手机存储，方便从相册拿图片：
   ```bash
   termux-setup-storage
   ```
   之后手机存储在 `~/storage/shared/` 下可见（如 `~/storage/shared/DCIM/`）。

## 安装 mssg

```bash
pip install mssg
```

v0.9.0 起基础安装只有 Markdown + Jinja2，Termux 里直接装得上。
需要图片压缩/代码高亮再加：

```bash
pip install "mssg[images]"      # 图片压缩/缩放（Pillow）
pip install "mssg[highlight]"   # 代码高亮（Pygments）
```

> 注意：Pillow 在 Termux 上 `pip install` 可能要现场编译，
> 时间较长；不装也不影响建站，只是图片直接拷贝不压缩。

## 建站 + 手机浏览器里写作

```bash
mssg new mysite
cd mysite
mssg admin
```

启动后会打印一个带 token 的地址，例如：

```
http://127.0.0.1:8902/?token=xxxx
```

**在手机浏览器（Chrome 等）里打开这个地址**——Termux 和手机共享
localhost，所以直接能访问。在后台里可以：

- 新建/编辑/删除文章（Markdown，所见即所得不用记语法也行）
- 点"构建"重新生成网站
- token 鉴权默认开启，同一台手机上用是安全的

想看效果：

```bash
mssg build
```

生成的静态网站在 `public/` 目录。

## 传图片

两种方式：

1. `termux-setup-storage` 之后，把手机相册的图拷进站点：
   ```bash
   cp ~/storage/shared/DCIM/Camera/xxx.jpg content/post/my-post/
   ```
   再在文章里用 `{{< image src="xxx.jpg" width="800" >}}` 引用
   （page bundle，构建时自动缩放）。
2. 在 `mssg admin` 里直接写 Markdown 引用 `static/` 下的图片。

## 发布到公网

手机上装了 git（前面 `pkg install git` 已装），`public/` 的内容
push 到 GitHub Pages / Netlify / Cloudflare Pages 即可：

```bash
cd public
git init && git add . && git commit -m "publish"
# 按托管商文档 push
```

## 已知限制

- iOS：App Store 不允许这类"可执行代码"的应用上架，
  这条路目前只适用于 Android。
- Termux 本身是个终端 App，第一次用需要适应；
  但日常写作发布都在手机浏览器里完成，不用再碰终端。
- 低端手机上构建大站（上千页）会慢一些，几十页的博客无压力。

DNGauge Linux 便携版
====================

1. 包内文件说明
---------------

- `DNGauge` : 主程序，可直接双击运行
- `DNGauge.desktop` : 带图标的文件夹内启动入口
- `DNGauge.png` : 程序图标 / 桌面图标
- `install_desktop_launcher.sh` : 安装桌面 / 应用菜单快捷方式
- `DNGauge.desktop.template` : 启动器模板

2. 如何启动
-----------

推荐方式：
1. 解压整个文件夹
2. 保持文件夹内文件在同一目录下
3. 直接双击 `DNGauge.desktop`

也可以：
- 直接双击 `DNGauge`

备用方式：
- 运行 `./DNGauge`

如果想安装桌面快捷方式：
1. 运行 `./install_desktop_launcher.sh`
2. 之后可以从桌面或应用菜单打开 `DNGauge`

3. 支持的输入格式
-----------------

- 普通图片：`jpg`、`jpeg`、`png`、`tif`、`tiff`、`bmp`、`webp`
- `rawpy/libraw` 支持的相机 RAW
- `dng`
- plain `.raw`

4. 主要按钮说明
---------------

顶部工具栏：

- `L↥` : 加载左图
- `R↥` : 加载右图
- `布局·单/双` : 单图 / 双图切换
- `同步·开/关` : 开启 / 关闭左右图同步缩放和平移
- `←` : 按住时把右图叠加到左图上，松开恢复
- `调参·开/关` : 显示 / 隐藏右侧调参面板
- `Locate·开/关` : 开启 / 关闭取样模式
- `Value:显示(渲染)` : 读取渲染后的 RGB / 灰度值
- `Value:RAW` : 读取 RAW 域原始值
- `通道·ALL / R / G1 / G2 / B` : 切换 RAW 通道显示
- `100%` : 按 1:1 比例查看
- `Fit` : 适配窗口显示

右侧图像调节面板：

- 曝光、对比度、饱和度、色温、色调、高光、阴影
- `重置` : 重置当前图像调节参数

右侧 RAW 调参面板：

- 通道
- 显示 Bit
- Black Level
- White Level
- Exposure Gain
- 白平衡开关
- `WB R / G / B`

5. 对比与数据读取
-----------------

- 左右图可以不是同一尺寸
- 对比时按比例映射坐标
- 底部信息栏会同时显示左图 / 右图的结果
- `Value:RAW` 会显示 RAW 值、坐标、通道和数据类型
- `Value:显示(渲染)` 会显示渲染后的 RGB / 灰度值

6. RAW 相关说明
---------------

- RAW 专属调参只对可编辑的 plain `.RAW` 生效
- 如果某一侧加载的是 `DNG`、`JPG`、`PNG` 或其他非 plain-RAW 图片，该侧 RAW 调参会自动禁用
- 如果 plain `.RAW` 不能被自动识别，程序会要求输入：
  宽、高、bit depth、Bayer pattern、packing 格式

7. 注意事项
-----------

- 不需要安装 Python / conda 环境
- 请不要把包内单个文件单独移走，整个文件夹保持在一起使用
- 如果 Linux 文件管理器限制 `.desktop` 启动器，可直接双击 `DNGauge` 主程序
- 安装桌面快捷方式后，应用菜单和桌面会显示 `DNGauge.png` 作为图标

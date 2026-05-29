# CDriveCleaner

一个偏保守的 Windows 11 C 盘清理小工具，目标是把最常见的“越用越满”的缓存和临时文件清理掉，同时尽量避免误删用户数据。

## 当前清理范围

- 当前用户临时目录 `%TEMP%`
- `C:\Windows\Temp`
- `C:\Windows\SoftwareDistribution\Download`
- `C:\ProgramData\Microsoft\Windows\DeliveryOptimization\Cache`
- `C:\Windows\Logs\CBS`
- `C:\Windows\Minidump`
- `C:\Windows\MEMORY.DMP`
- 回收站

## 安全策略

- 不处理桌面、下载、文档、图片、视频等用户文件夹
- 不删除应用程序安装目录
- 用户临时目录和 Windows 临时目录默认只清理至少 1 天前的文件
- 文件被占用、权限不足时自动跳过，不会强制结束进程

## 编译

在 PowerShell 中执行：

```powershell
Set-Location D:\project\LibreDWG\tools\CDriveCleaner
.\build.ps1
```

生成文件：

`D:\project\LibreDWG\tools\CDriveCleaner\dist\CDriveCleaner.exe`

## 使用建议

- 想清理系统更新缓存时，建议以管理员身份运行
- 先点“扫描可清理空间”，确认体积后再点“执行清理”
- 如果你的 C 盘是被微信、QQ、浏览器、开发工具缓存占满，这个版本还没覆盖到，可以继续扩展

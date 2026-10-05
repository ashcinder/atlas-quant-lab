# 编译 Linux amd64 版本
$env:GOOS="linux"
$env:GOARCH="amd64"
$env:CGO_ENABLED="0"

# 输出文件名
$OUTPUT="bin\supervisor"

# 编译
go build -o $OUTPUT

if ($LASTEXITCODE -eq 0) {
    Write-Host "Build success: $OUTPUT (linux/amd64)"
} else {
    Write-Host "Build failed"
}

# V2-07 Ubuntu 服务器初始化与安全加固

## 1. 边界

以下命令必须在购买服务器后由用户在真实服务器执行。涉及 SSH、云防火墙和系统权限的步骤不可盲目自动化。推荐 Ubuntu 24.04 LTS，Ubuntu 22.04 LTS 也在 Docker 官方支持范围内。

官方参考：

- Docker Ubuntu 安装：<https://docs.docker.com/engine/install/ubuntu/>
- Ubuntu OpenSSH：<https://ubuntu.com/server/docs/how-to/security/openssh-server/>
- Ubuntu UFW：<https://ubuntu.com/server/docs/how-to/security/firewalls/>

## 2. 创建部署用户

在云厂商初始管理员会话中执行，替换 `<deploy-user>`：

```bash
sudo adduser <deploy-user>
sudo usermod -aG sudo <deploy-user>
sudo install -d -m 0700 -o <deploy-user> -g <deploy-user> /home/<deploy-user>/.ssh
sudoedit /home/<deploy-user>/.ssh/authorized_keys
sudo chmod 0600 /home/<deploy-user>/.ssh/authorized_keys
sudo chown <deploy-user>:<deploy-user> /home/<deploy-user>/.ssh/authorized_keys
```

在本地另开终端验证密钥登录成功：

```bash
ssh <deploy-user>@<server-ip>
sudo -v
```

只有验证成功并保留一个已登录救援会话后，才考虑在 `/etc/ssh/sshd_config.d/99-hardening.conf` 设置：

```text
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
```

先执行 `sudo sshd -t`，确认返回 0，再 `sudo systemctl reload ssh`，并用第三个新终端重新登录验证。任何一步失败都不要关闭现有会话。这里不提供会在未验证密钥时自动锁死 SSH 的脚本。

## 3. 系统基础设置

```bash
sudo timedatectl set-timezone Asia/Shanghai
sudo apt update
sudo apt upgrade
sudo apt install ca-certificates curl openssl python3 logrotate ufw
sudo systemctl enable --now systemd-timesyncd
```

内核或关键库升级后按维护窗口重启并验证：

```bash
sudo reboot
```

## 4. 安装 Docker Engine 与 Compose

以下步骤来自 Docker 官方 apt 仓库说明。若服务器无法稳定访问该仓库，改用官方 `.deb` 离线安装路径或在可信网络准备包，不要随意配置第三方镜像加速器。

```bash
sudo apt update
sudo apt install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

```bash
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt update
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker version
sudo docker compose version
```

Docker socket 等价于高权限入口。默认运维脚本使用 `sudo`；不要把 socket 暴露到 TCP，不要挂载给应用容器，不要把无关用户加入 `docker` 组。

## 5. 防火墙

先在云厂商安全组中只开放 TCP 80、443；TCP 22 建议只允许固定办公/家庭出口 IP。再配置主机 UFW。替换 `<trusted-ip>`，并先 dry-run：

```bash
sudo ufw --dry-run allow proto tcp from <trusted-ip> to any port 22
sudo ufw --dry-run allow 80/tcp
sudo ufw --dry-run allow 443/tcp
```

确认规则不会锁死 SSH 后执行：

```bash
sudo ufw allow proto tcp from <trusted-ip> to any port 22
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status verbose
```

Docker 发布端口可能绕过部分 UFW 预期，因此还必须核对云安全组和 `docker compose ps`。生产 Compose 只发布 80/443；8000、SQLite 和 Worker 均不发布。

## 6. 目录与发布包

```bash
sudo install -d -m 0755 /opt/insightflow/releases
sudo install -d -m 0750 /srv/insightflow
```

本地把发布包上传到服务器后：

```bash
sudo install -d -m 0755 /opt/insightflow/releases/<版本>
sudo tar -xzf insightflow-<版本>.tar.gz -C /opt/insightflow/releases/<版本>
sudo ln -sfn /opt/insightflow/releases/<版本> /opt/insightflow/current
cd /opt/insightflow/current
```

压缩包不得包含 `.env`、数据库、证书、备份、上传、报告、字体或密钥。

## 7. 系统级运维

安装示例 timer 和 logrotate 前先检查其中固定路径：

```bash
sudo install -m 0644 deploy/systemd/insightflow-*.service /etc/systemd/system/
sudo install -m 0644 deploy/systemd/insightflow-*.timer /etc/systemd/system/
sudo install -m 0644 deploy/logrotate/insightflow /etc/logrotate.d/insightflow
sudo systemctl daemon-reload
sudo systemctl enable --now insightflow-backup.timer insightflow-health.timer
sudo systemctl enable --now insightflow-cleanup-dry-run.timer
sudo systemctl list-timers 'insightflow-*'
```

配置云厂商磁盘使用率告警，建议 80% 预警、90% 紧急处理；同时监控内存和实例可达性。不要暴露 Docker socket，不运行无关数据库、面板和开发服务器，定期安装安全更新并在维护窗口重启。

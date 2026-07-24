# V2-07 域名、ICP备案、DNS 与 HTTPS

## 1. 不能由代码完成的事项

域名购买、实名认证、ICP备案、公安联网备案、DNS 修改和证书签发都需要用户及接入商/主管部门参与。本仓库没有执行这些操作，也不代表已经审核通过。

工信主管部门说明非经营性互联网信息服务可通过接入商备案系统提交，接入商核验后由省级通信管理局审核；网站开通后应按要求在主页展示备案编号并链接备案系统：

- <https://beian.miit.gov.cn/>
- <https://www.miit.gov.cn/zwgk/zcwj/flfg/art/2020/art_4c6a91eb93c34a6e8adc5852f9b56fd1.html>

实际材料、时限、前置审批和公安联网备案要求以主办主体所在地、接入商和主管部门当期规则为准。

## 2. 推荐顺序

1. 在国内合规注册商购买域名并完成实名认证；
2. 购买明确支持备案的中国内地服务器；
3. 在云厂商/接入商备案系统提交 ICP 备案；
4. 等待核验和审核，不假设必然通过；
5. 备案完成后设置域名 A 记录指向服务器公网 IPv4；
6. 使用 `dig +short <域名>` 和不同网络确认 DNS 生效；
7. 申请证书并启动生产 Compose；
8. 在网站底部展示真实备案号及查询链接；
9. 按当地公安机关和云厂商要求办理公安联网备案并展示编号。

## 3. DNS 与应用变量

DNS 控制台人工添加：

```text
类型：A
主机记录：@ 或实际子域
记录值：<服务器公网 IPv4>
TTL：使用服务商合理默认值
```

生产环境中：

```text
PUBLIC_SITE_URL=https://<域名>
CORS_ORIGINS=https://<域名>
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=lax
AUTH_COOKIE_DOMAIN=
```

同域单主机建议 `AUTH_COOKIE_DOMAIN` 留空，使用 host-only Cookie。只有确实需要跨子域共享时才填写不带 scheme/端口的父域，并重新评估安全边界。

## 4. HTTPS 方案 A：已有证书

把云厂商或 CA 提供的证书以 PEM 形式放到：

```text
/srv/insightflow/secrets/tls/fullchain.pem
/srv/insightflow/secrets/tls/privkey.pem
```

```bash
sudo install -d -m 0700 /srv/insightflow/secrets/tls
sudo install -m 0644 <fullchain-source> /srv/insightflow/secrets/tls/fullchain.pem
sudo install -m 0600 <private-key-source> /srv/insightflow/secrets/tls/privkey.pem
sudo openssl x509 -noout -subject -issuer -dates \
  -in /srv/insightflow/secrets/tls/fullchain.pem
```

证书私钥不得进入 Git、发布包、普通备份或部署日志。更新后执行：

```bash
cd /opt/insightflow/current
sudo bash deploy/scripts/reload-nginx.sh
```

脚本先验证证书可解析和 `nginx -t`，再平滑 reload。

## 5. HTTPS 方案 B：ACME/Certbot

只有备案要求已满足、A 记录已指向本机、DNS 已生效且公网 80 端口可达时，HTTP-01 才可能成功。Certbot 官方文档说明 webroot/standalone 的 HTTP-01 使用 80 端口，renew 后应使用 deploy hook：

- <https://eff-certbot.readthedocs.io/en/stable/using.html>
- <https://letsencrypt.org/docs/allow-port-80/>

首次签发时生产 Nginx 尚未启动，可在服务器人工执行：

```bash
sudo apt update
sudo apt install certbot
sudo certbot certonly --standalone -d <域名> -m <邮箱> --agree-tos
sudo install -m 0644 /etc/letsencrypt/live/<域名>/fullchain.pem \
  /srv/insightflow/secrets/tls/fullchain.pem
sudo install -m 0600 /etc/letsencrypt/live/<域名>/privkey.pem \
  /srv/insightflow/secrets/tls/privkey.pem
```

启动应用后，Nginx 已为 `/.well-known/acme-challenge/` 保留 webroot。将续期 hook 安装到固定位置并先 dry-run：

```bash
sudo install -m 0755 deploy/scripts/certbot-deploy-hook.sh \
  /etc/letsencrypt/renewal-hooks/deploy/insightflow
sudo certbot renew --dry-run
```

hook 只在成功续期后复制新证书、验证配置并平滑 reload。若发布目录不是 `/opt/insightflow/current`，先调整 hook 中的运行位置或使用包装脚本。

## 6. Nginx HTTPS 行为

- 80 除 ACME challenge 外全部 301 到 HTTPS；
- TLS 只启用 1.2/1.3；
- 443 正式环境启用一年 HSTS；
- `/api` 传递 Host、真实 IP、转发链和 HTTPS scheme；
- 前端/后端同时设置不破坏 SSE 的 CSP 和其他安全头。

HSTS 会让浏览器记住 HTTPS。域名、证书、HTTPS 全链路未验证前不要在测试域提前长期启用；本生产模板只面向正式 HTTPS。

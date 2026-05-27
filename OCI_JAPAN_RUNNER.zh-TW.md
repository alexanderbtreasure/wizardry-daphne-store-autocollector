# OCI Japan Runner SOP

[[English](OCI_JAPAN_RUNNER.md) | 繁體中文]

這份 SOP 會建立一台日本地區的 Oracle Cloud Free Tier VM，並把它註冊成 `.github/workflows/jp-autocollector.yml` 使用的 GitHub Actions runner。

## 1. 建立 Oracle VM

使用 Oracle Cloud Free Tier 帳號，不要升級到 Pay As You Go。未升級的 Free Tier 帳號在試用期後不能建立付費資源，這是避免意外費用的做法。Oracle Always Free 資源只要維持在 Oracle 限制內，試用期後仍可繼續使用。

Oracle 註冊時會要求有效信用卡，這是帳號驗證用。保持 Free Tier，不要升級帳號。

建立一台 VM：

1. 登入 Oracle Cloud Console。
2. 確認右上角 region selector。使用 `Japan Central (Osaka)`。如果帳號已固定在 Tokyo，就使用 `Japan East (Tokyo)`。
3. 開啟 `Menu -> Compute -> Instances`。
4. 點 `Create instance`。
5. Instance name 填 `wvd-jp-runner`。
6. `Placement` 保持預設 availability domain。
7. 在 `Image and shape` 點 `Edit`。
8. Image 選 `Oracle Linux 10`。
9. Shape 選 `VM.Standard.E2.1.Micro`，確認畫面標示 Always Free-eligible。
10. `Networking` 選 `Create new virtual cloud network`。VCN 與 public subnet 名稱保持 Oracle 預設。確認 `Assign a public IPv4 address` 已啟用，這會建立 SSH 需要的 1 個 public VNIC。
11. `Add SSH keys` 選 `Paste public keys`，貼上本機 SSH public key，通常是 `~/.ssh/id_ed25519.pub` 的內容。
12. `Boot volume` 設成 `50 GB`。
13. 展開 `Show advanced options -> Management -> Initialization script`。
14. 貼上 [cloud-init/oci-github-runner.yml](cloud-init/oci-github-runner.yml) 的完整內容。
15. 點 `Create`。

點 `Create` 之前，GUI 應該顯示這些最低設定：

- OS：Oracle Linux 10
- Shape：`VM.Standard.E2.1.Micro`
- Network：1 個 VNIC，在 public subnet，並啟用 public IPv4
- Boot volume：50 GB

建立後等 instance state 變成 `Running`。打開 instance details，複製 `Public IPv4 address`。在自己的電腦用文字編輯器打開 `~/.ssh/config`，加入：

```sshconfig
Host oc_gitrunner
  HostName YOUR_PUBLIC_IPV4
  User opc
  IdentityFile ~/.ssh/id_ed25519
```

測試 SSH：

```sh
ssh oc_gitrunner
```

不要花時間搶 `VM.Standard.A1.Flex`。2026 年在熱門區域幾乎拿不到 Always Free A1.Flex 容量，這個 runner 使用 `VM.Standard.E2.1.Micro` 加 swap。

## 2. 確認 Cloud-Init

建立 instance 的步驟已經把 [cloud-init/oci-github-runner.yml](cloud-init/oci-github-runner.yml) 貼到 Oracle Cloud initialization script 欄位。

cloud-init 會做這些事：

- 安裝基本套件
- 下載 GitHub runner 到 `/home/opc/actions-runner`
- 套用 Oracle Linux SELinux runner 修正
- 建立持久化的 2 GB `/swapfile`
- 新增每週一 10:00 UTC 的預先重開機 cron

cloud-init 不會 clone 這個 repository。workflow 會用 `actions/checkout@v6` 自己 checkout。

第一次開機後，SSH 進 VM 確認 cloud-init 完成：

```sh
ssh oc_gitrunner
sudo tail -n 80 /var/log/cloud-init-output.log
cat /root/wvd-runner-next-steps.txt
```

## 3. 註冊 GitHub Runner

在 GitHub 打開：

`Settings -> Actions -> Runners -> New self-hosted runner`

選擇：

- Runner image：`Linux`
- Architecture：`x64`

複製 GitHub 產生的 `./config.sh --url ... --token ...` 指令。

在 VM 上執行：

```sh
cd ~/actions-runner
./config.sh --url https://github.com/exkuretrol/wizardry-daphne-store-autocollector --token YOUR_TOKEN --labels oci,jp
```

安裝並啟動 runner service：

```sh
sudo ./svc.sh install opc
sudo chcon -R -t bin_t /home/opc/actions-runner
sudo ./svc.sh start
sudo ./svc.sh status
```

預期狀態包含：

```text
Active: active (running)
Runner.Listener run --startuptype service
```

## 4. 新增 GitHub Secrets

在 GitHub 打開：

`Settings -> Secrets and variables -> Actions -> New repository secret`

新增兩個 secrets：

```text
WIZARDRY_JP_EMAIL
WIZARDRY_JP_PASSWORD
```

workflow 會直接用環境變數傳入 secrets，所以密碼內有 `$` 也沒問題。

## 5. 確認 Runner Labels

workflow 指定：

```yaml
runs-on: [self-hosted, linux, oci, jp]
```

在 GitHub 確認 runner 顯示這些 labels：

```text
self-hosted
linux
oci
jp
```

## 6. 測試 Workflow

手動執行 workflow：

`Actions -> Japan Webstore Autocollector -> Run workflow`

已領取時的成功輸出範例：

```text
Summary: {'VvQwG2KoMz82': 'already', 'D6Vj2rYxMjne': 'already'}
exit_code=0
```

workflow 會在啟動 Chromium 前執行 `Ensure swap`。

## 7. 確認重開機 Cron

VM 應該每週一 10:00 UTC 重開機，比 collector 排程 11:00 UTC 早一小時。

確認：

```sh
sudo crontab -l
```

預期有這一行：

```cron
0 10 * * 1 /usr/sbin/reboot # wvd-pre-run-reboot
```

## 安全注意事項

不要讓這台 self-hosted runner 跑不可信任的 pull request。self-hosted runner 會在 VM 上執行 workflow code。JP 憑證只放在 GitHub Actions secrets。

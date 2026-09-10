# 生產的模型密鑰是無效的，AI 審查整條路是斷的（2026-09-10）

## 怎麼發現的

批准花錢之後，我把 agent 事實抽取跑向一份真實文件，拿到 HTTP 401。先確認不是我的
環境問題：

| 檢查 | 我的臨時容器 | 生產 API 容器 |
|---|---|---|
| 解析到的密鑰長度 | 116 | 116 |
| baseUrl | dashscope.aliyuncs.com/compatible-mode/v1 | 同 |
| `review-chat` 解析到 | official_api:qwen3.7-plus | 同 |
| 直接發一次 chat | **HTTP 401** | **HTTP 401** |

**生產 API 容器自己也調不動模型。** 這不是我引入的。

## 阿里雲回的原文

```json
{"error":{"message":"Incorrect API key provided. ...",
  "type":"invalid_request_error","code":"invalid_api_key"},
 "request_id":"05c0eef7-c3cd-96d2-b3f8-9d84297b9f81"}
```

`AICHECK_LLM_API_KEY` 的值是 `sk-ws-` 開頭、116 字元。DashScope 的 API key 不長
這樣。這個變數裡放的很可能根本不是 DashScope 的密鑰。

## 三條路全查了，三條都不通

在三個容器（api / worker-llm / ocr-service）裡逐一比對密鑰的前綴與長度：

| 變數 | 前綴 | 長度 | 供應商 | 實測 |
|---|---|---|---|---|
| `AICHECK_LLM_API_KEY` | `sk-ws-H…` | 116 | DashScope | **401 invalid_api_key** |
| `AICHECK_LLM_VISION_API_KEY` | `sk-ws-H…` | 116 | DashScope | **401 invalid_api_key**（和上面同一把） |
| `AICHECK_LLM_FALLBACK_API_KEY`＝`DEEPSEEK_API_KEY` | `sk-41526…` | 35 | DeepSeek | **402 Insufficient Balance** |
| `LITELLM_API_KEY` | `sk-Iasyo…` | 47 | LiteLLM | **代理容器沒在跑**（`docker ps -a` 也沒有） |

所以：

- **通義那把是無效的密鑰**（不是餘額問題，阿里雲明說 `invalid_api_key`）。
  `sk-ws-` 開頭、116 字元，不是 DashScope API key 的形狀。視覺角色用的是同一把，
  所以視覺也一起壞了。
- **DeepSeek 那把密鑰是好的，但賬戶沒錢**（402 Insufficient Balance）。
  9 月 3 日那 112 次 deepseek-v4-pro 成功就是走這條，之後餘額用完了。
- LiteLLM 的虛擬密鑰還在，但代理根本沒有這個容器。

另外 `aicheck-runtime.env` 的修改時間是 **2026-09-10 18:08**（今天）。倉庫裡沒有任
何腳本會寫這個檔（`grep` 過），最近的備份還停在 8 月——**是有人今天手動改過**。
改了什麼無從比對，但值得問一句。

## 從什麼時候開始的

`model_call_attempts` 的歷史：

| 狀態 | 模型 | 最後一次 | 次數 |
|---|---|---|---|
| success | deepseek-v4-pro | 2026-09-03 18:35 | 112 |
| success | qwen3.7-plus | 2026-09-04 02:04 | 48 |
| success | qwen3.8-max | **2026-09-09 04:11** | 22 |
| failed (IntegrationServiceError) | document-classifier | **2026-09-10 04:12** | 3 |

最後一次成功是 9 月 9 日 04:11，今天 04:12 的文件分類就開始失敗。**中間某個時間
點密鑰失效了，而沒有任何人被通知。**

## 影響

凡是要調模型的功能現在全都不能用：AI 審查、一鍵分析、文件自動分類。前兩者現在沒
人在跑所以沒人發現；文件分類今天失敗了 3 次。

## 我不能修

- 使用者明確要求：**絕不手改** `/home/dev-bjy/aicheck-runtime.env`
- 我手上沒有有效的 DashScope 密鑰

**DeepSeek 已由項目方棄用**（2026-09-10 確認），所以那條 402 不必處理，它也不再
是可用的回退。**唯一的路是通義**：需要在阿里雲百煉控制台簽一把新的 API key
（`sk-` 開頭、約 35 字元那種），寫進 `AICHECK_LLM_API_KEY`，再重啟 API 與四個
worker 容器。視覺角色目前和主角色共用同一把無效密鑰，換的時候要一併考慮。

順帶一提：DeepSeek 棄用之後，`AICHECK_LLM_FALLBACK_*` 那組配置就是死重。留著它
的壞處是主供應商出問題時，錯誤會先變成一次 402 再冒出來，看起來像餘額問題而不是
密鑰問題——今天就差點誤導我。建議清掉，但這要動 runtime.env，不歸我做。

## 順帶暴露的問題：密鑰失效沒有告警

`_deployment_probes` 和既有巡檢沒有一項會發現「模型調不動」。建議加一條探針：
定期發一次最小的 chat 請求，401/403 就告警。密鑰過期是會反覆發生的事，靠人偶然
撞見不是辦法。

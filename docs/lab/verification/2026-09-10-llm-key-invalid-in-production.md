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

沒有 `AICHECK_LLM_PROJECT_REVIEW_API_KEY`，所以 `projectReview` 角色也回落到同一
把密鑰，一樣 401。視覺角色另有 `AICHECK_LLM_VISION_API_KEY`，沒測。

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

要恢復，需要有人在阿里雲百煉控制台簽發一把新的 API key，寫進
`AICHECK_LLM_API_KEY`，然後重啟 API 與 worker 容器。

## 順帶暴露的問題：密鑰失效沒有告警

`_deployment_probes` 和既有巡檢沒有一項會發現「模型調不動」。建議加一條探針：
定期發一次最小的 chat 請求，401/403 就告警。密鑰過期是會反覆發生的事，靠人偶然
撞見不是辦法。

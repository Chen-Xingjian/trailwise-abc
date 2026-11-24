# 本地运行、CI与部署规则

## 1. 默认部署：本机Mac

本轮目标是Apple Silicon Mac上的本地最小原型。应用默认只监听 `127.0.0.1`，浏览器与FastAPI同源；模型服务同样保持本机访问。项目启动与API路径以根目录README及配置示例为准。

本轮启动器使用 MLX-LM，模型兼容接口为 `http://127.0.0.1:8081/v1`，应用页面为 `http://127.0.0.1:8765`。LM Studio 仍可作为兼容运行器，其常用端口为 `1234`；端口及实际模型 ID 必须和应用配置一致。连接成功、模型实际已加载、检索路径可用分别检查，不把 HTTP 服务启动当作模型运行成功。[LM Studio文档](https://lmstudio.ai/docs/developer/openai-compat)、[MLX-LM文档](https://github.com/ml-explore/mlx-lm)。

Mac 设置入口为 `python3.12 scripts/setup_mac.py --install`。它在 `~/Library/Caches/Trailwise/nepal-trail-rag/` 创建 `fresh-venv` 和 `model-runtime`，按 `requirements/constraints-mac.txt` 安装 `dev,embeddings,mlx,download` 依赖；不移动项目原环境，也不建立目录符号链接。激活该环境后执行 `python scripts/download_models.py`，下载位置默认是上述 `model-runtime`；固定 revision 在 `config/model_pins.json`，实际 snapshot 位置记录在缓存内的 `model_snapshots.json`。

使用 `python scripts/launch_local.py`，或在完成初始化后双击 `run-local.command`，启动器会选择 Caches 的环境、模型快照与派生索引，设定 CPU embedding 及单进程应用。终端 Ctrl+C 会停止模型和应用两个进程。`run-local.command` 不自动安装依赖或下载模型。

本机发现 `Documents` 被 iCloud FileProvider 管理，旧环境和权重会变成按需下载文件，导致导入和加载等待。因此，把大量可重建生成物放在本机 Caches，代码、受控数据及审核历史仍保留在项目中。原 `.venv/` 与 `runtime/` 保留为 gitignored 的旧生成目录，不是当前启动器的活动环境或模型依据；不自动删除它们。

Caches 不是审核资料的唯一保存位置。依赖、权重和索引可以依据固定版本重建；接受的事实 release、人工审核事件及评估记录应另行保存、版本管理和备份。清理缓存后重新设置/下载，不从旧目录静默恢复未确认资料。普通 Linux CI 继续只安装基础开发依赖，不采用 Mac 设置入口。不要把模型下载、模型 API 调用或需要大内存的整合测试放进普通 CI，也不把权重或索引放入 Git。

Qdrant Local适合首轮单进程应用。多个服务进程不得同时把同一磁盘目录当作各自可写本地索引；如果需要并发或云端服务，另行评估Qdrant服务端及存储管理，再迁移与验收。公开网页也不能直接连接本机模型或本地向量库。

## 2. GitHub Actions首轮配置

`.github/workflows/ci.yml` 只执行可重复的离线质量检查：

1. 固定Python 3.12，安装开发依赖。
2. 检查受控release：事实/来源哈希、接受状态、字段白名单、排除项与依赖。
3. 运行Ruff和pytest，验证应用、范围边界、错误处理及数据选择。

触发为pull request、推送main及手动运行。使用最小 `contents: read` 权限、取消同分支旧运行、超时限制，以及完整commit SHA固定第三方Action。SHA来自官方仓库ref API读取，不能凭记忆填写：checkout v4 `11d5960a326750d5838078e36cf38b85af677262`；setup-python v5 `a26af69be951a213d495a4c3e4e4022e16d87065`（2026-11-18观察）。版本更新应人工审查后替换。[GitHub安全建议](https://docs.github.com/en/actions/reference/security/secure-use)。

普通CI不读取LM Studio、不使用Mac模型服务、不下载权重、不要求模型token，也不自动部署。CI通过只证明已执行的代码和数据检查通过，不能证明RAG优于基线。

## 3. 人工模型整合与发布门槛

真实模型整合测试在已审查的本地代码上手动运行，记录模型/量化/runner、embedding revision、数据release、参数、耗时及原始输出。将来若使用self-hosted runner，只允许明确的手动受信任任务；不能让外部PR自动执行在个人Mac上。该工作流当前不启用。

每轮交付须有：通过的静态与业务检查、资料和范围说明、真实运行状态、错误分析，以及用户对本轮变化的验收。新模型或新语料不能因已有CI绿色状态自动获得接受。保留上一版manifest、配置和可重建索引，部署失败时回到匹配的一组版本。

## 4. 公共部署的决定

首轮不做公网发布。需要老师远程演示时，先在受控本机演示或分享经过许可核查的运行记录。若以后明确需要公网应用，先确定托管资源、真实成本与访问人群，并完成以下具体实现和检查后再请求最终发布决定：

- HTTPS与访问控制，模型API和数据库不能直接暴露。
- 输入长度、输出token、请求频率、并发、超时和错误信息限制；后端密钥留在服务端。
- 精确来源范围、数据许可与署名展示；对外分享改写文本的BY-SA义务按对应资料处理，不把所有代码或模型一概改成同一许可。
- 日志最小化、明确保留周期、避免默认收集完整个人行程和会话；健康、实时天气及当前通行仍按现有范围处理。
- 受控release校验、模型与embedding兼容性、持久化卷与备份/回滚、基本可用性检查。

本地界面不能直接由GitHub Pages承载完整推理服务；它只托管静态资源，后端和模型仍需独立可用的运行环境。不要把部署设计误写成已经公开上线的结果。

## ABC weather and trail updates

On this Mac, run `./run-abc-live.command` and open `http://127.0.0.1:8765`. This entry uses the 84-record public subset in [documents/abc-six-day](../documents/abc-six-day). To select another reviewed package explicitly, set `DATA_RELEASE_DIR` before starting the launcher. The original launcher uses its configured release. The server binds to loopback. The model and vector index run locally. Weather and notice requests send public lookup parameters to their respective publishers. User questions and personal information stay on the Mac.

In the English question box, try “Forecast for Deurali tomorrow from 07:00 to 10:00” or “Is the ABC trail currently open?” Reply in the same chat to supply a missing date, reference point or walking window. A point forecast describes one model grid neighbourhood. A question about a whole stage with no representative point prompts for the missing location in the conversation. Forecast subqueries sent through the UI use the educational, on-demand service. Existing offline comparison scripts omit `offer_live_checks`; baseline mode skips live tools. Frozen R38 scores refer to the earlier offline evaluation.

For a point and date alone, the app requests daily temperature extremes, precipitation, snowfall and peak gusts from the Open-Meteo Forecast API in Nepal time. The daily response records the lookup time. The provider does not supply a model run timestamp in that response.

For an explicit walking window the app requests one DWD ICON Global run at a time through [Open-Meteo Single Runs](https://open-meteo.com/en/docs/single-runs-api). The application tries six-hour model cycles newest first and accepts runs no older than 18 hours for walks up to three Nepal calendar days ahead. These are application limits, not a provider freshness guarantee. It checks the complete model hours bracketing the selected window, units, time zone, target elevation and a maximum 15 km grid offset. The requested elevation is used for downscaling. It is not a measurement at the trail or the native elevation of the grid. Snowfall is a prediction; the accepted G07 card separately explains when recent local snow or ice reports justify considering traction on the upper trail. Model initialisation, lookup time and valid hours are shown separately. Missing data or a failed request cannot produce a current forecast.

The [Nepal Tourism Board situation feed](https://trade.ntb.gov.np/category/situation-updates/feed/) supplies bulletin titles, original links and publication dates. It is an English corridor-mention discovery source with limited recent entries. A mention, an empty feed result, and the time of retrieval all leave access unverified. Read the full issuing notice, check its section, affected users and effective period, and consult the [ACAP office](https://ntnc.org.np/project/annapurna-conservation-area-project-acap) for local confirmation. The page links separately to [Nepal DHM bulletins](https://www.dhm.gov.np/). Weather and trail bulletins are checked on demand. The source-change checker below monitors the frozen knowledge base separately. Neither forecasts nor bulletins enter the long-term fact index.

Weather attribution: DWD ICON Global via [Open-Meteo](https://open-meteo.com/), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), selected hours and ranges. The free endpoint is for [non-commercial use](https://open-meteo.com/en/terms). The three query anchors are adapted from [KeiTreks GPX](https://keitreks.com/gpx), CC BY 4.0. They match the accepted S05 audit endpoints for days 1, 3 and 4.

### Source changes and local observations

The ABC launcher starts a supervised source checker while the local application is running. It checks for due work hourly, including on startup. Static source targets are revisited every seven days, archived ERA5 inputs every 30 days, and failed requests after one day. Closing the app or sleeping the Mac delays checks until it runs again. The chat looks up current forecasts and notices on demand. Set `ABC_SOURCE_WATCH=0` for an offline run.

Open **Our coverage → Reviewed source changes** for per-target timestamps, unavailable sources and affected fact IDs. The public package maps all 84 facts to public targets. Binary GPX/CSV hashes, six ABC timing labels, the current Wikivoyage revision and ERA5 data (excluding processing time) have archived comparison values. OSM objects and NPS/CDC page text begin with a first-lookup comparison baseline. They can detect later source changes. That first lookup does not certify agreement with the old audit. HTML navigation/layout changes and upstream editorial revisions may produce alerts even if a fact is still correct.

In the repository, `python -m app.source_watch --release "$DATA_RELEASE_DIR" --runtime runtime --force` performs a manual check using the project Python environment. Each scan is stored under `runtime/source-watch/<release manifest SHA-256>/`. The JSON links targets to affected records and retains unavailable and changed states separately. Scans never change the release or reindex facts. After checking the original diff and every affected record, the reviewer can record that the facts are unaffected using the same command with `--affirm-unaffected TARGET OBSERVED_FINGERPRINT "reviewer's reason"` instead of `--force`. For a substantive change, prepare a revised fact with its new provenance, run the normal data audit and release a new version. Recheck the target definitions and archived comparison hashes when preparing a new release.

The local source lookup also checks the [Annapurna Rural Municipality tourism notice listing](https://visit.annapurnamunkaski.org/notices/). It preserves Nepalese titles and links without inferring the affected section from a title. Use the [NTNC support directory](https://epermit.ntnc.org.np/support) for Chhomrong Checkpost or Ghandruk ACAP, and the [municipal accommodation directory](https://visit.annapurnamunkaski.org/accomodations/) for businesses at Deurali and MBC. A directory entry identifies whom to ask. Neither directory is a field observation. No automated calls or messages are sent.

For a traceable, operator-reviewed, public field report, import a JSON file with `python -m app.trail_updates /path/to/report.json`. Supply `section` (ABC corridor, Deurali to MBC, or MBC to ABC), `subject` (pedestrians, vehicles, or pack animals), `publisher`, `source_url`, `observation`, `observed_at`, `published_at`, and optionally `valid_until`. Use documented timezone-aware timestamps. If the time of observation cannot be established, leave the source as a lead instead of inventing a timestamp. Review the exact location, issuer, affected users, source permissions and observation first. Store a short statement in your own words. Reports are separate from the fact index; expired or undated-validity reports remain labelled. Reports from different dates or reporters remain separately attributable. A crossing seen at a particular time cannot establish later access.

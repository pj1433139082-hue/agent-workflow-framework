# 通用文档交付：虚构演示

draft → validate → complete 是本地协作状态，不是模型部署阶段或外部收件人的确认。

1. draft：填写 payload.json 的 audience、purpose 与 draft.md，synthetic 保持 true，去掉占位内容。
2. validate：按用途完成 final.md，审查事实、范围与读者可用性；实际接受后记录 review-acceptance=accept。需要修订时答 revise，流程不会完成。
3. complete：本地交付文件准备完成。外部发消息、发布、客户签收均需另行实现和明确任务范围。

正文存在且没有占位只证明结构准备完成，不证明事实正确。三种档位均不推断业务答案；换智能体仍读取同一任务事实和资料。

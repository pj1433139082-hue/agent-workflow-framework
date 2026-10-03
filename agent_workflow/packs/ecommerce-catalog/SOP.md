# 电商商品资料审核：虚构演示

这不是预测模型或店铺连接器。collect → review → ready 只表示本地协作进度，ready 不表示商品上架。

1. collect：填写当前任务的 payload.json，sku/title 非空、price 为有限正数、currency 为 CNY、synthetic 保持 true。初始模板不是已确认资料。
2. review：记录 review.md 的检查结论、问题和依据，去掉 TODO/待填写占位；只有阅读后的实际回答才可记录 review-acceptance。revise 会阻止完成。
3. ready：交付本地审核资料。真实上架、调价、订单、退款和支付均不在本业务包中。

自动检查只能验证字段和资料结构，不替代真实性、合规性或质量审查。将本包用于其他货币、真实商品或平台操作时，应另立业务包和验收标准，不关闭检查冒充已支持。

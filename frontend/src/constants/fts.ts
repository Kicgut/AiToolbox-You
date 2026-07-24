export const FTS_NOTICE_VERSION = 1;

export const FTS_NOTICE = `全文索引会把会话文本的脱敏副本保存在本机 data/ai_workbench/workbench.db。

当前脱敏只能识别常见密钥模式，不能保证发现所有敏感内容。

你可以随时“关闭未来索引”来停止后续写入；已有内容会保留，直到点击“清空已有索引”。

是否接受以上说明并开启全文索引？`;

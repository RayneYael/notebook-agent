interface EmptyProps {
  trueFirstEmpty: boolean;
  onAdd?: () => void;
}

export function LibraryEmptyState({ trueFirstEmpty, onAdd }: EmptyProps) {
  if (!trueFirstEmpty) {
    return (
      <section className="state-card state-card--compact">
        <p className="eyebrow">搜索结果</p>
        <h2>没有符合条件的视频</h2>
        <p>换一个关键词，或清除筛选后再看看。</p>
      </section>
    );
  }
  return (
    <section className="state-card welcome-card">
      <div className="agent-mark" aria-hidden="true">N</div>
      <p className="eyebrow">Notebook Agent</p>
      <h2>我是你的资料整理助手。</h2>
      <p>把想长期保存的 YouTube 链接交给我，我会在后台整理字幕、章节和可检索内容。</p>
      {onAdd ? <button className="button button--primary" onClick={onAdd}>添加第一个视频</button> : null}
    </section>
  );
}

export function LibraryLoadingState() {
  return (
    <div className="skeleton-list" aria-label="正在加载资料库" aria-busy="true">
      {[0, 1, 2].map((index) => <div className="video-skeleton" key={index} />)}
    </div>
  );
}

export function LibraryErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <section className="state-card state-card--compact" role="alert">
      <p className="eyebrow">连接中断</p>
      <h2>暂时无法读取资料库</h2>
      <p>你的数据没有丢失。检查网络后重新加载即可。</p>
      <button className="button button--quiet" onClick={onRetry}>重新加载</button>
    </section>
  );
}

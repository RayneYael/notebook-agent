import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  listLibraryItems,
  submitVideoBatch,
  type LibraryQuery,
} from "../api/client";
import type { BatchSubmitInput, BatchSubmitResponse, LibraryPageResponse } from "../api/contracts";
import { AddVideosDialog } from "./AddVideosDialog";
import { LibraryEmptyState, LibraryErrorState, LibraryLoadingState } from "./LibraryStates";
import { shouldPollLibrary } from "./lifecycle";
import { VideoCard } from "./VideoCard";

interface LibraryPageProps {
  fetchItems?: (query: LibraryQuery) => Promise<LibraryPageResponse>;
  submitBatch?: (input: BatchSubmitInput) => Promise<BatchSubmitResponse>;
}

export function LibraryPage({
  fetchItems = listLibraryItems,
  submitBatch = submitVideoBatch,
}: LibraryPageProps) {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [searchDraft, setSearchDraft] = useState("");
  const [search, setSearch] = useState("");
  const [lifecycle, setLifecycle] = useState("");
  const [sort, setSort] = useState<LibraryQuery["sort"]>("saved_desc");
  const [page, setPage] = useState(1);
  const query: LibraryQuery = {
    search,
    lifecycle,
    include_archived: lifecycle === "archived",
    sort,
    page,
    page_size: 20,
  };
  const library = useQuery({
    queryKey: ["library", query],
    queryFn: () => fetchItems(query),
    retry: 1,
    refetchInterval: (state) => shouldPollLibrary(state.state.data?.items ?? []) ? 4_000 : false,
  });
  const totalPages = library.data ? Math.max(1, Math.ceil(library.data.total / library.data.page_size)) : 1;

  function changeFilter(next: string) {
    setLifecycle(next);
    setPage(1);
  }

  return (
    <>
      <section className="library-heading">
        <div>
          <p className="eyebrow">私人资料库</p>
          <h1>你真正想留下的内容</h1>
          <p>视频在后台整理。你可以离开页面，稍后回来继续阅读。</p>
        </div>
        <button className="button button--primary" onClick={() => setDialogOpen(true)}>添加视频</button>
      </section>

      <section className="library-toolbar" aria-label="资料库筛选">
        <form
          className="search-box"
          role="search"
          onSubmit={(event) => { event.preventDefault(); setSearch(searchDraft.trim()); setPage(1); }}
        >
          <label className="sr-only" htmlFor="library-search">搜索标题、作者或保存原因</label>
          <input id="library-search" name="search" type="search" autoComplete="off" value={searchDraft} onChange={(event) => setSearchDraft(event.target.value)} placeholder="搜索标题、作者或保存原因" />
          <button type="submit" aria-label="搜索">↗</button>
        </form>
        <label className="select-field">
          <span className="sr-only">状态</span>
          <select name="lifecycle" value={lifecycle} onChange={(event) => changeFilter(event.target.value)}>
            <option value="">全部状态</option>
            <option value="ready">可阅读</option>
            <option value="queued">等待处理</option>
            <option value="processing">正在整理</option>
            <option value="needs_action">需要处理</option>
            <option value="failed">处理失败</option>
            <option value="archived">已归档</option>
          </select>
        </label>
        <label className="select-field">
          <span className="sr-only">排序</span>
          <select name="sort" value={sort} onChange={(event) => { setSort(event.target.value as LibraryQuery["sort"]); setPage(1); }}>
            <option value="saved_desc">最近保存</option>
            <option value="saved_asc">最早保存</option>
            <option value="title_asc">标题排序</option>
          </select>
        </label>
      </section>

      {library.isPending ? <LibraryLoadingState /> : null}
      {library.isError ? <LibraryErrorState onRetry={() => void library.refetch()} /> : null}
      {library.isSuccess && library.data.items.length === 0 ? (
        <LibraryEmptyState trueFirstEmpty={library.data.is_true_first_empty && !search && !lifecycle} onAdd={() => setDialogOpen(true)} />
      ) : null}
      {library.isSuccess && library.data.items.length > 0 ? (
        <>
          <div className="library-summary"><span>{library.data.total} 个视频</span>{shouldPollLibrary(library.data.items) ? <span className="live-note"><i />状态自动更新中</span> : null}</div>
          <div className="video-grid">
            {library.data.items.map((item) => <VideoCard item={item} key={item.public_id} />)}
          </div>
          {totalPages > 1 ? (
            <nav className="pagination" aria-label="资料库分页">
              <button className="button button--ghost" disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>上一页</button>
              <span>{page} / {totalPages}</span>
              <button className="button button--ghost" disabled={page >= totalPages} onClick={() => setPage((value) => value + 1)}>下一页</button>
            </nav>
          ) : null}
        </>
      ) : null}

      <AddVideosDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        submitBatch={submitBatch}
        onSubmitted={() => void queryClient.invalidateQueries({ queryKey: ["library"] })}
      />
    </>
  );
}

// Design notes (commitment):
// Movement: Swiss modernism + utilitarian industrial UI
// Principles: dense information, crisp typography, sharp borders, high contrast, no gradients
// Color: near-white background, ink foreground, acid green accent
// Motifs: grid lines, status pills, monospace job id

import { useMemo, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import { Loader2, Upload, Download, Copy, Link as LinkIcon } from "lucide-react";

type SingleResponse = {
  mode: "single";
  job_id: string;
  records: number;
  files: {
    business_xlsx: string;
    review_xlsx: string;
  };
};

type CompareResponse = {
  mode: "compare";
  job_id: string;
  records: { engine_a: number; engine_b: number };
  files: {
    engine_a_business_xlsx: string;
    engine_a_review_xlsx: string;
    engine_b_business_xlsx: string;
    engine_b_review_xlsx: string;
    compare_xlsx: string;
  };
};

type ParseResponse = SingleResponse | CompareResponse;

function joinUrl(base: string, path: string) {
  const b = base.replace(/\/$/, "");
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${b}${p}`;
}

function DownloadLink({ label, url, onCopy, accent }: { label: string; url: string; onCopy: (t: string) => void; accent?: boolean }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm">
          <Download className="h-4 w-4" />
          {label}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" className="rounded-none" onClick={() => onCopy(url)}>
            <LinkIcon className="mr-2 h-4 w-4" />复制链接
          </Button>
          <Button
            className={`rounded-none ${accent ? "bg-[oklch(0.77_0.23_145)] text-black hover:bg-[oklch(0.77_0.23_145)]" : ""}`}
            onClick={() => window.open(url, "_blank")}
          >
            下载
          </Button>
        </div>
      </div>
      <div className="text-xs text-muted-foreground font-mono break-all border border-border p-2 rounded-none">
        {url}
      </div>
    </div>
  );
}

export default function Home() {
  const [apiBase, setApiBase] = useState(() => {
    return (import.meta as any).env?.VITE_API_BASE || window.location.origin;
  });
  const [rulesPath, setRulesPath] = useState("rules/dataset_2603.yml");
  const [saleDate, setSaleDate] = useState("");
  const [lang, setLang] = useState("ch");
  const [startOrderNo, setStartOrderNo] = useState("");
  const [mode, setMode] = useState<"single" | "compare">("single");
  const [file, setFile] = useState<File | null>(null);

  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ParseResponse | null>(null);

  const isCompare = result?.mode === "compare";

  const businessUrl = useMemo(() => {
    if (!result) return "";
    if (isCompare) return joinUrl(apiBase, result.files.engine_a_business_xlsx);
    return joinUrl(apiBase, result.files.business_xlsx);
  }, [apiBase, result]);

  const reviewUrl = useMemo(() => {
    if (!result) return "";
    if (isCompare) return joinUrl(apiBase, result.files.engine_a_review_xlsx);
    return joinUrl(apiBase, result.files.review_xlsx);
  }, [apiBase, result]);

  const engineBBusinessUrl = useMemo(() => {
    if (!result || !isCompare) return "";
    return joinUrl(apiBase, result.files.engine_b_business_xlsx);
  }, [apiBase, result]);

  const engineBReviewUrl = useMemo(() => {
    if (!result || !isCompare) return "";
    return joinUrl(apiBase, result.files.engine_b_review_xlsx);
  }, [apiBase, result]);

  const compareUrl = useMemo(() => {
    if (!result || !isCompare) return "";
    return joinUrl(apiBase, result.files.compare_xlsx);
  }, [apiBase, result]);

  async function onSubmit() {
    if (!file) {
      toast.error("请先选择一张账本图片");
      return;
    }

    setLoading(true);
    setResult(null);

    try {
      const form = new FormData();
      form.append("file", file);
      form.append("rules_path", rulesPath);
      form.append("lang", lang);
      form.append("mode", mode);
      if (saleDate.trim()) form.append("sale_date", saleDate.trim());
      if (startOrderNo.trim()) form.append("start_order_no", startOrderNo.trim());

      const { data } = await axios.post<ParseResponse>(joinUrl(apiBase, "/v1/parse"), form, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 10 * 60 * 1000,
      });

      setResult(data);
      const recCount = data.mode === "compare"
        ? `引擎A: ${data.records.engine_a} 行, 引擎B: ${data.records.engine_b} 行`
        : `${data.records} 行`;
      toast.success(`解析完成：${recCount}`);
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || "请求失败";
      toast.error(`解析失败：${msg}`);
    } finally {
      setLoading(false);
    }
  }

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast.success("已复制到剪贴板");
    } catch {
      toast.error("复制失败（可能是浏览器权限限制）");
    }
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border">
        <div className="mx-auto max-w-6xl px-6 py-8">
          <div className="flex items-end justify-between gap-6 flex-wrap">
            <div>
              <div className="inline-flex items-center gap-2">
                <span className="h-2 w-2 rounded-none bg-[oklch(0.77_0.23_145)]" />
                <span className="text-xs tracking-[0.2em] uppercase text-muted-foreground">img2ledger</span>
              </div>
              <h1 className="mt-3 text-3xl md:text-4xl font-semibold tracking-tight">
                手写账本 → Excel
              </h1>
              <p className="mt-2 text-sm md:text-base text-muted-foreground max-w-2xl">
                通过 API 上传账本图片，自动解析并返回可下载的 Excel（业务版 / 校对版）。
              </p>
            </div>

            <div className="flex items-center gap-2">
              <Badge variant="secondary" className="rounded-none">PoC UI</Badge>
              <Badge className="rounded-none bg-[oklch(0.77_0.23_145)] text-black hover:bg-[oklch(0.77_0.23_145)]">
                /v1/parse
              </Badge>
              <Badge variant="outline" className="rounded-none">
                {mode === "compare" ? "对比模式" : "单引擎"}
              </Badge>
            </div>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-10">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          <Card className="rounded-none border-border lg:col-span-7">
            <CardHeader>
              <CardTitle className="text-base tracking-wide">上传与解析</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="api">API Base</Label>
                  <Input
                    id="api"
                    value={apiBase}
                    onChange={(e) => setApiBase(e.target.value)}
                    placeholder="http://localhost:8000"
                    className="rounded-none"
                  />
                  <p className="text-xs text-muted-foreground">
                    服务地址（例如 <span className="font-mono">http://localhost:8000</span>）。若前后端同域反代，可留默认。
                  </p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="rules">rules_path</Label>
                  <Input
                    id="rules"
                    value={rulesPath}
                    onChange={(e) => setRulesPath(e.target.value)}
                    placeholder="rules/dataset_2603.yml"
                    className="rounded-none"
                  />
                  <p className="text-xs text-muted-foreground">
                    解析规则文件路径（服务端可访问）。
                  </p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="date">sale_date（可选）</Label>
                  <Input
                    id="date"
                    value={saleDate}
                    onChange={(e) => setSaleDate(e.target.value)}
                    placeholder="2026-03-20"
                    className="rounded-none"
                  />
                  <p className="text-xs text-muted-foreground">不填则由服务端自行推断（若实现了文件名映射）。</p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="lang">lang</Label>
                  <Input
                    id="lang"
                    value={lang}
                    onChange={(e) => setLang(e.target.value)}
                    placeholder="ch"
                    className="rounded-none"
                  />
                  <p className="text-xs text-muted-foreground">PaddleOCR 语言代号（默认 ch）。</p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="orderNo">start_order_no（可选）</Label>
                  <Input
                    id="orderNo"
                    value={startOrderNo}
                    onChange={(e) => setStartOrderNo(e.target.value)}
                    placeholder="起始单号，如 001"
                    className="rounded-none"
                  />
                  <p className="text-xs text-muted-foreground">不填则由服务端自行推断。</p>
                </div>

                <div className="space-y-2 md:col-span-2">
                  <Label>mode</Label>
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      variant={mode === "single" ? "default" : "outline"}
                      className={`rounded-none ${mode === "single" ? "bg-[oklch(0.77_0.23_145)] text-black hover:bg-[oklch(0.77_0.23_145)]" : ""}`}
                      onClick={() => setMode("single")}
                    >
                      单引擎
                    </Button>
                    <Button
                      type="button"
                      variant={mode === "compare" ? "default" : "outline"}
                      className={`rounded-none ${mode === "compare" ? "bg-[oklch(0.77_0.23_145)] text-black hover:bg-[oklch(0.77_0.23_145)]" : ""}`}
                      onClick={() => setMode("compare")}
                    >
                      双引擎对比
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {mode === "compare"
                      ? "同时运行主引擎和 Baseline 引擎（并行），输出差异对照表"
                      : "仅使用主引擎解析"}
                  </p>
                </div>
              </div>

              <Separator />

              <div className="space-y-3">
                <Label>账本图片</Label>
                <div className="flex flex-col md:flex-row gap-3 md:items-center">
                  <Input
                    type="file"
                    accept="image/*"
                    onChange={(e) => setFile(e.target.files?.[0] || null)}
                    className="rounded-none"
                  />
                  <Button
                    onClick={onSubmit}
                    disabled={loading}
                    className="rounded-none bg-[oklch(0.77_0.23_145)] text-black hover:bg-[oklch(0.77_0.23_145)]"
                  >
                    {loading ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        解析中…
                      </>
                    ) : (
                      <>
                        <Upload className="mr-2 h-4 w-4" />
                        上传并解析
                      </>
                    )}
                  </Button>
                </div>

                {file ? (
                  <div className="text-xs text-muted-foreground flex items-center gap-2">
                    <span className="inline-block h-1.5 w-1.5 bg-foreground" />
                    <span className="font-mono">{file.name}</span>
                    <span>·</span>
                    <span>{Math.round(file.size / 1024)} KB</span>
                  </div>
                ) : (
                  <div className="text-xs text-muted-foreground">支持 JPG/PNG。建议拍照保持正面、清晰、避免阴影。</div>
                )}
              </div>
            </CardContent>
          </Card>

          <Card className="rounded-none border-border lg:col-span-5">
            <CardHeader>
              <CardTitle className="text-base tracking-wide">结果与下载</CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              {!result ? (
                <div className="space-y-3">
                  <div className="text-sm">还没有结果。</div>
                  <div className="text-xs text-muted-foreground leading-relaxed">
                    上传成功后，服务将返回一个 <span className="font-mono">job_id</span>，并提供 Excel 下载链接。
                    {mode === "compare" && (
                      <>
                        <br />对比模式下会同时输出双引擎结果及差异对照表。
                      </>
                    )}
                  </div>
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-xs text-muted-foreground">job_id</div>
                      <div className="font-mono text-sm">{result.job_id}</div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant={isCompare ? "default" : "secondary"} className={`rounded-none ${isCompare ? "bg-[oklch(0.77_0.23_145)] text-black" : ""}`}>
                        {isCompare ? "对比模式" : "单引擎"}
                      </Badge>
                      <Button variant="outline" className="rounded-none" onClick={() => copy(result.job_id)}>
                        <Copy className="mr-2 h-4 w-4" />
                        复制
                      </Button>
                    </div>
                  </div>

                  {isCompare ? (
                    <div className="grid grid-cols-2 gap-3">
                      <div className="border border-border p-3 rounded-none">
                        <div className="text-xs text-muted-foreground">引擎A 行数</div>
                        <div className="text-2xl font-semibold tabular-nums">{(result as CompareResponse).records.engine_a}</div>
                      </div>
                      <div className="border border-border p-3 rounded-none">
                        <div className="text-xs text-muted-foreground">引擎B 行数</div>
                        <div className="text-2xl font-semibold tabular-nums">{(result as CompareResponse).records.engine_b}</div>
                      </div>
                    </div>
                  ) : (
                    <div className="grid grid-cols-2 gap-3">
                      <div className="border border-border p-3 rounded-none">
                        <div className="text-xs text-muted-foreground">解析行数</div>
                        <div className="text-2xl font-semibold tabular-nums">{(result as SingleResponse).records}</div>
                      </div>
                      <div className="border border-border p-3 rounded-none">
                        <div className="text-xs text-muted-foreground">接口</div>
                        <div className="font-mono text-sm">/v1/parse</div>
                      </div>
                    </div>
                  )}

                  <Separator />

                  {!isCompare && (
                    <>
                      <DownloadLink label="business.xlsx" url={businessUrl} onCopy={copy} />
                      <DownloadLink label="review.xlsx" url={reviewUrl} onCopy={copy} />
                    </>
                  )}

                  {isCompare && (
                    <>
                      <div className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">引擎 A（主引擎）</div>
                      <DownloadLink label="business.xlsx" url={businessUrl} onCopy={copy} />
                      <DownloadLink label="review.xlsx" url={reviewUrl} onCopy={copy} />

                      <div className="text-xs font-semibold tracking-wide text-muted-foreground uppercase pt-2">引擎 B（Baseline）</div>
                      <DownloadLink label="business.xlsx" url={engineBBusinessUrl} onCopy={copy} />
                      <DownloadLink label="review.xlsx" url={engineBReviewUrl} onCopy={copy} />

                      <Separator />
                      <div className="text-xs font-semibold tracking-wide text-[oklch(0.77_0.23_145)] uppercase">差异对照</div>
                      <DownloadLink label="compare.xlsx" url={compareUrl} onCopy={copy} accent />
                    </>
                  )}

                  <div className="text-xs text-muted-foreground leading-relaxed">
                    如果浏览器提示跨域（CORS），请在服务端允许该前端域名，或通过同域反向代理部署。
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="mt-10 border-t border-border pt-6 text-xs text-muted-foreground flex flex-col md:flex-row md:items-center md:justify-between gap-3">
          <div>
            前端仅封装上传/下载；解析逻辑在后端服务。
            <span className="ml-2 font-mono">/v1/parse</span>
          </div>
          <div className="font-mono">建议：将 API 与前端做同域部署，避免 CORS。</div>
        </div>
      </main>
    </div>
  );
}

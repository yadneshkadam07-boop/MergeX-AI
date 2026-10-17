import { useMutation } from "@tanstack/react-query";
import { FileArchive, FolderGit2, Loader2, PlayCircle, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { createAnalysis } from "@/api/analyses";
import { ApiError } from "@/api/client";
import { importDemo, importGitHub, uploadZip, type ProjectCreateResponse } from "@/api/projects";
import { AppShell } from "@/components/AppShell";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

const CAPABILITIES = [
  ["API contracts", "Every frontend call matched against the routes the backend defines."],
  ["Schema drift", "ORM models and raw SQL checked against the migrations that ran."],
  ["Security", "Hardcoded secrets, auth gaps, CORS, debug mode, vulnerable pins."],
] as const;

/**
 * Import a project and start analysing it.
 *
 * Importing and analysing are two backend calls, but one action as far as a
 * user is concerned, so they are chained here and the page navigates
 * straight to the live run.
 */
export function LandingPage() {
  const navigate = useNavigate();
  const fileInput = useRef<HTMLInputElement>(null);

  const [url, setUrl] = useState("");
  const [ref, setRef] = useState("");
  const [dragging, setDragging] = useState(false);

  const start = useMutation({
    mutationFn: async (project: ProjectCreateResponse) => {
      const analysis = await createAnalysis(project.project.id);
      return analysis.id;
    },
    onSuccess: (analysisId) => navigate(`/analyses/${analysisId}`),
  });

  const github = useMutation({
    mutationFn: () => importGitHub(url.trim(), ref.trim() || undefined),
    onSuccess: (project) => start.mutate(project),
  });

  const upload = useMutation({
    mutationFn: (file: File) => uploadZip(file),
    onSuccess: (project) => start.mutate(project),
  });

  const demo = useMutation({
    mutationFn: () => importDemo(),
    onSuccess: (project) => start.mutate(project),
  });

  const busy = github.isPending || upload.isPending || demo.isPending || start.isPending;
  const failure = github.error ?? upload.error ?? demo.error ?? start.error;

  const describe = (error: unknown): string => {
    if (error instanceof ApiError) return error.message;
    if (error instanceof TypeError) {
      return "Could not reach the MergeX API. Check that the backend is running.";
    }
    return error instanceof Error ? error.message : "The import failed.";
  };

  const chooseFile = (file: File | undefined) => {
    if (file) upload.mutate(file);
  };

  return (
    <AppShell className="max-w-5xl">
      <div className="space-y-10 py-6">
        <section className="space-y-4">
          <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">
            Do your layers actually fit together?
          </h1>
          <p className="text-muted-foreground max-w-2xl text-lg">
            MergeX imports a repository and compares its frontend, backend and database against each
            other — the defects that only appear where two layers meet, and that no single-layer
            linter can see.
          </p>
        </section>

        {failure ? (
          <ErrorState title="Could not start the analysis" message={describe(failure)} />
        ) : null}

        <Card>
          <CardHeader>
            <CardTitle>Import a project</CardTitle>
            <CardDescription>
              Nothing is executed. The code is cloned into a sandbox, read, and deleted.
            </CardDescription>
          </CardHeader>

          <CardContent>
            <Tabs defaultValue="github">
              <TabsList className="mb-4">
                <TabsTrigger value="github">
                  <FolderGit2 className="size-4" aria-hidden />
                  GitHub URL
                </TabsTrigger>
                <TabsTrigger value="zip">
                  <FileArchive className="size-4" aria-hidden />
                  ZIP upload
                </TabsTrigger>
              </TabsList>

              <TabsContent value="github">
                <form
                  className="space-y-4"
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (url.trim()) github.mutate();
                  }}
                >
                  <div className="grid gap-4 sm:grid-cols-[1fr_12rem]">
                    <div className="space-y-2">
                      <Label htmlFor="repo-url">Repository URL</Label>
                      <Input
                        id="repo-url"
                        value={url}
                        onChange={(event) => setUrl(event.target.value)}
                        placeholder="https://github.com/owner/repo"
                        autoComplete="off"
                        spellCheck={false}
                        disabled={busy}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="repo-ref">Branch or tag (optional)</Label>
                      <Input
                        id="repo-ref"
                        value={ref}
                        onChange={(event) => setRef(event.target.value)}
                        placeholder="main"
                        autoComplete="off"
                        spellCheck={false}
                        disabled={busy}
                      />
                    </div>
                  </div>

                  <Button type="submit" disabled={busy || !url.trim()}>
                    {github.isPending || start.isPending ? (
                      <Loader2 className="size-4 animate-spin" aria-hidden />
                    ) : (
                      <FolderGit2 className="size-4" aria-hidden />
                    )}
                    Analyse repository
                  </Button>
                  <p className="text-muted-foreground text-xs">
                    Public github.com repositories only, up to 100 MB.
                  </p>
                </form>
              </TabsContent>

              <TabsContent value="zip">
                <div
                  onDragOver={(event) => {
                    event.preventDefault();
                    setDragging(true);
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={(event) => {
                    event.preventDefault();
                    setDragging(false);
                    chooseFile(event.dataTransfer.files[0]);
                  }}
                  className={cn(
                    "flex flex-col items-center gap-3 rounded-xl border border-dashed px-6 py-12 text-center transition-colors",
                    dragging ? "border-ring bg-accent" : "border-border",
                  )}
                >
                  <Upload className="text-muted-foreground size-6" aria-hidden />
                  <p className="text-sm font-medium">Drop a .zip here</p>
                  <p className="text-muted-foreground text-xs">or choose one from your machine</p>
                  <input
                    ref={fileInput}
                    type="file"
                    accept=".zip,application/zip"
                    className="sr-only"
                    aria-label="Project archive"
                    onChange={(event) => chooseFile(event.target.files?.[0])}
                    disabled={busy}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => fileInput.current?.click()}
                    disabled={busy}
                  >
                    {upload.isPending ? (
                      <Loader2 className="size-4 animate-spin" aria-hidden />
                    ) : (
                      <FileArchive className="size-4" aria-hidden />
                    )}
                    Choose archive
                  </Button>
                </div>
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>

        <Card className="border-dashed">
          <CardContent className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
            <div className="space-y-1">
              <p className="font-medium">No repository to hand?</p>
              <p className="text-muted-foreground text-sm">
                Analyse the bundled React + FastAPI project. It has real seeded defects: a mistyped
                API path, a method mismatch, a camelCase payload and an unauthenticated call to a
                protected route.
              </p>
            </div>
            <Button
              variant="secondary"
              onClick={() => demo.mutate()}
              disabled={busy}
              className="shrink-0"
            >
              {demo.isPending || (start.isPending && demo.isSuccess) ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <PlayCircle className="size-4" aria-hidden />
              )}
              Load demo
            </Button>
          </CardContent>
        </Card>

        <dl className="grid gap-5 sm:grid-cols-3">
          {CAPABILITIES.map(([term, description]) => (
            <div key={term} className="space-y-1.5">
              <dt className="text-sm font-medium">{term}</dt>
              <dd className="text-muted-foreground text-sm">{description}</dd>
            </div>
          ))}
        </dl>
      </div>
    </AppShell>
  );
}

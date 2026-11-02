export interface ReportSection {
  id: string;
  title: string;
  markdown: string;
}

export interface ProjectReport {
  generatedAt: string;
  sections: ReportSection[];
}

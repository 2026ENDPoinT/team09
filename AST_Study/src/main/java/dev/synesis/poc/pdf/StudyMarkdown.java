package dev.synesis.poc.pdf;

import org.commonmark.node.Image;
import org.commonmark.node.Link;
import org.commonmark.node.Node;
import org.commonmark.node.Paragraph;
import org.commonmark.node.Code;
import org.commonmark.node.FencedCodeBlock;
import org.commonmark.node.IndentedCodeBlock;
import org.commonmark.node.SourceSpan;
import org.commonmark.ext.gfm.tables.TablesExtension;
import org.commonmark.ext.gfm.tables.TableBlock;
import org.commonmark.parser.Parser;
import org.commonmark.parser.IncludeSourceSpans;
import org.commonmark.renderer.html.HtmlRenderer;
import org.scilab.forge.jlatexmath.TeXConstants;
import org.scilab.forge.jlatexmath.TeXFormula;
import org.scilab.forge.jlatexmath.TeXIcon;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Renders model-authored study Markdown without allowing document HTML or remote images. */
final class StudyMarkdown {
    private static final Parser PARSER = Parser.builder().extensions(List.of(TablesExtension.create()))
        .includeSourceSpans(IncludeSourceSpans.BLOCKS_AND_INLINES).build();
    private static final HtmlRenderer HTML = HtmlRenderer.builder().escapeHtml(true).sanitizeUrls(true)
        .extensions(List.of(TablesExtension.create())).softbreak("<br>").build();
    private static final Pattern MATH = Pattern.compile(
        "(?s)\\$\\$(.+?)\\$\\$|\\\\\\[(.+?)\\\\\\]|\\\\\\((.+?)\\\\\\)|(?<!\\\\)\\$(?!\\s)([^\\n$]+?)(?<!\\s)\\$");
    // Older saved summaries use plain square brackets instead of LaTeX inline delimiters.
    private static final Pattern BRACKETED_MATH = Pattern.compile("\\[([^\\[\\]\\n]{1,240})\\](?!\\()");
    private static final Pattern BRACKETED_INTERVAL = Pattern.compile(
        "\\[((?:-?[0-9]+(?:\\.[0-9]+)?|[A-Za-z]),\\s*\\\\infty)\\)");
    // Models occasionally omit inline delimiters around a Greek symbol or trig function.
    // Keep this narrow: arbitrary TeX commands in prose must not become executable math.
    private static final Pattern BARE_MATH = Pattern.compile(
        "(?<![A-Za-z0-9\\\\:/])((?:\\\\(?:sin|cos|tan))?\\\\(?:alpha|beta|gamma|delta|Delta|epsilon|varepsilon|theta|vartheta|lambda|mu|nu|pi|rho|sigma|Sigma|tau|phi|varphi|omega|Omega)"
        + "|\\\\(?:vec|hat|mathbf|boldsymbol|overrightarrow|overline|sqrt)\\{[^{}]{1,80}\\}"
        + "|\\\\(?:frac|dfrac)\\{[^{}]{1,80}\\}\\{[^{}]{1,80}\\})(?![A-Za-z])");
    private static final Pattern BARE_TEX_PARENS = Pattern.compile("\\(([^()\\n]{1,240})\\)");
    private static final Pattern MATH_COMMAND = Pattern.compile(
        "\\\\(?:vec|hat|mathbf|boldsymbol|overrightarrow|overline|sqrt|frac|dfrac|sum|int|deg|ln|log|ldots|cdots|approx|mathrm|"
        + "alpha|beta|gamma|delta|Delta|epsilon|varepsilon|theta|vartheta|lambda|mu|nu|pi|rho|sigma|Sigma|tau|phi|varphi|omega|Omega|sin|cos|tan)(?![A-Za-z])");
    private static final Pattern UNSAFE_TEX = Pattern.compile(
        "(?i)\\\\(?:includegraphics|input|include|openin|openout|read|write|catcode|def|newcommand|href|url|html|special)\\b");
    private static final String MATH_ATOM = "(?:\\\\[A-Za-z]+(?:\\{[^{}]*\\})?|\\([^()]*\\)|[A-Za-z0-9]+(?:,[0-9]{3})*(?:\\.[0-9]+)?)";
    private static final String MATH_FACTOR = MATH_ATOM + "(?:\\^(?:\\{[^{}]+\\}|[A-Za-z0-9]+))?";
    private static final Pattern SIMPLE_DIVISION = Pattern.compile(
        "(?<![A-Za-z0-9\\\\])(" + MATH_FACTOR + ")\\s*/\\s*(" + MATH_FACTOR + ")(?![A-Za-z0-9])");
    private static final Pattern CODE_HTML = Pattern.compile("(?s)<pre\\b[^>]*>.*?</pre>|<code\\b[^>]*>.*?</code>");
    private static final Pattern PROTECTED_HTML = Pattern.compile(CODE_HTML.pattern()+"|<[^>]+>", Pattern.DOTALL);
    private static final Pattern KOREAN_SENTENCE_BREAK = Pattern.compile("(?<=[가-힣])\\.\\s+(?=\\S)");
    private static final Pattern ANSI_CSI = Pattern.compile("\u001b\\[[0-?]*[ -/]*[@-~]");
    private static final Pattern ORPHAN_ANSI_SGR = Pattern.compile("\\[(?:\\?|[0-9;]{1,12})m");
    private static final Pattern LITERAL_ESC_CLOSER = Pattern.compile("\\\\u001b(?=[)\\]])");
    private static final Pattern UNDELIMITED_MATH_TOKEN = Pattern.compile(
        "(?<![A-Za-z0-9\\\\:/])(?:[A-Za-z0-9_+*/=^{}()\\[\\].,;|<>−-]|[α-ωΑ-Ω∫∑√∞≈≤≥×·₀-₉ₐₑₒₓₕₖₗₘₙₚₛₜ⁰¹²³⁴⁵⁶⁷⁸⁹ⁿⁱᵃᵇ⁺⁻⁽⁾₊₋₍₎]|\\\\(?:[A-Za-z]+|[,;:])){2,240}");
    private static final Pattern UNICODE_MATH = Pattern.compile("[α-ωΑ-Ω∫∑√∞₀-₉ₐₑₒₓₕₖₗₘₙₚₛₜ⁰¹²³⁴⁵⁶⁷⁸⁹ⁿⁱᵃᵇ]");
    private static final Pattern OPAQUE_MARKER = Pattern.compile("SYNESIS(?:MATH|CODE)[A-Za-z0-9]+N[0-9]+END");
    private static final Map<String, ScrollableMath> SCROLLABLE_MATH = new LinkedHashMap<>(128, .75f, true) {
        @Override protected boolean removeEldestEntry(Map.Entry<String, ScrollableMath> eldest) {
            return size() > 1024;
        }
    };

    record ScrollableMath(String html, int width, int height) {}
    private record FormulaKey(String tex,int fontSize,boolean display,boolean dark) {}
    private record FormulaLayout(String html,String id,ScrollableMath scroll,int width) {}
    private static final Map<FormulaKey,FormulaLayout> FORMULA_LAYOUTS = new LinkedHashMap<>(128,.75f,true) {
        @Override protected boolean removeEldestEntry(Map.Entry<FormulaKey,FormulaLayout> eldest) {
            return size()>1024;
        }
    };

    static ScrollableMath scrollableMath(String id) {
        synchronized (SCROLLABLE_MATH) { return SCROLLABLE_MATH.get(id); }
    }

    private StudyMarkdown() {}

    static String render(String markdown, int fontSize) {
        return render(markdown, fontSize, false);
    }

    /** Render a short label with the same safe Markdown and math handling as study prose. */
    static String renderInline(String markdown, int fontSize) {
        if (markdown == null || markdown.isBlank()) return "";
        String rendered = render(markdown.replace('\n', ' ').replace('\r', ' '), fontSize).strip();
        // Swing button labels do not understand MathML; show a readable text equivalent.
        rendered = rendered.replaceAll("(?s)<math\\b[^>]*data-plain='([^']*)'[^>]*>.*?</math>", "$1");
        if (rendered.startsWith("<p>") && rendered.endsWith("</p>"))
            return rendered.substring(3, rendered.length() - 4);
        return rendered;
    }

    static String render(String markdown, int fontSize, boolean dark) {
        return render(markdown, fontSize, dark, 0);
    }

    static String renderWithScrollableMath(String markdown, int fontSize) {
        return render(markdown, fontSize, false, -1);
    }

    static String renderWithScrollableMath(String markdown,int fontSize,boolean dark,int availableWidth) {
        return render(markdown,fontSize,dark,Math.max(1,availableWidth-24));
    }

    private static String render(String markdown, int fontSize, boolean dark, int mathWidth) {
        if (markdown == null || markdown.isBlank()) return "";
        markdown = stripAnsiSequences(markdown);
        String nonce = UUID.randomUUID().toString().replace("-", "");
        String pipeMarker = "SYNESISTABLEPIPE" + nonce + "N0END";
        // GFM consumes one backslash before a cell's pipe. Math is extracted
        // before the final Markdown parse, so unwrap that same escape once into
        // a temporary literal marker first, never a different TeX delimiter.
        markdown = protectTablePipes(markdown, pipeMarker);
        markdown = breakLongProseParagraphs(markdown);
        // CommonMark identifies code precisely (including nested and tilde fences).
        // Protect its source before math/bold repair; restore before HTML rendering.
        List<int[]> codeRanges = new ArrayList<>();
        collectCodeRanges(PARSER.parse(markdown), codeRanges);
        codeRanges.sort((a, b) -> Integer.compare(a[0], b[0]));
        String codePrefix = "SYNESISCODE" + nonce + "N";
        String mathPrefix = "SYNESISMATH" + nonce + "N";
        List<String> codeSources = new ArrayList<>();
        for (int[] range : codeRanges) codeSources.add(withoutControlChars(markdown.substring(range[0], range[1])));
        for (int i = codeRanges.size()-1; i >= 0; i--) {
            int[] range = codeRanges.get(i);
            markdown = markdown.substring(0, range[0]) + codePrefix + i + "END" + markdown.substring(range[1]);
        }
        // Some model JSON responses use paired FS/ESC controls around math instead of LaTeX delimiters.
        // Repair these only after protecting code, then discard all remaining control characters.
        markdown = restoreSplitIntegral(withoutControlChars(repairJsonEscapedMathCommands(
            restoreBracketedMathOutsideExplicit(normalizeDoubleEscapedMath(restoreDamagedInlineClosers(restoreControlMath(markdown)))))));
        // A lone missing star is a common model typo in otherwise valid bold Markdown.
        markdown = markdown.replaceAll("(?<!\\*)\\*([^*\\n]{2,80})\\*\\*", "**$1**");
        Matcher matcher = MATH.matcher(markdown);
        StringBuffer prepared = new StringBuffer();
        List<String> replacements = new ArrayList<>();
        while (matcher.find()) {
            String formula = null;
            for (int i = 1; i <= 4; i++) if (matcher.group(i) != null) { formula = matcher.group(i); break; }
            formula = formula == null ? null : formula.replace(pipeMarker, "|");
            if (matcher.group(4) != null && !isInlineFormula(formula)) {
                matcher.appendReplacement(prepared, Matcher.quoteReplacement(matcher.group()));
                continue;
            }
            boolean display = matcher.group(1) != null || matcher.group(2) != null;
            if(display)formula=quotedFormula(repairDisplayMathLayout(formula),markdown,matcher.start());
            String marker = mathPrefix + replacements.size() + "END";
            replacements.add(formulaHtml(formula, matcher.group().replace(pipeMarker,"|"), fontSize, display, dark, mathWidth));
            matcher.appendReplacement(prepared, Matcher.quoteReplacement(marker));
        }
        matcher.appendTail(prepared);
        // The model sometimes writes comparison commands directly in prose.
        // Explicit math and code have already been replaced with opaque markers.
        String proseWithComparisons=StudyUnicodeMath.restore(prepared.toString(),(formula,original)->{
            String marker=mathPrefix+replacements.size()+"END";
            replacements.add(formulaHtml(formula,original,fontSize,false,dark,mathWidth));
            return marker;
        });
        for(String command:new String[]{"leq","le"})proseWithComparisons=Pattern.compile(
            Pattern.quote("\\"+command)+"(?![A-Za-z])").matcher(proseWithComparisons).replaceAll("≤");
        for(String command:new String[]{"geq","ge"})proseWithComparisons=Pattern.compile(
            Pattern.quote("\\"+command)+"(?![A-Za-z])").matcher(proseWithComparisons).replaceAll("≥");
        // Some older tutor answers put TeX inside ordinary parentheses instead of \(...\).
        // Turn only recognisable mathematical expressions into one image, before atom repair.
        Matcher bareParentheses = BARE_TEX_PARENS.matcher(proseWithComparisons);
        StringBuffer groupedMath = new StringBuffer();
        while (bareParentheses.find()) {
            String formula = bareParentheses.group(1).replace(pipeMarker,"|");
            if (formula.matches(".*[가-힣:].*") || !MATH_COMMAND.matcher(formula).find()
                    || formula.matches(".*\\s+[A-Za-z]{3,}\\s+.*")) {
                bareParentheses.appendReplacement(groupedMath, Matcher.quoteReplacement(bareParentheses.group()));
                continue;
            }
            String marker = mathPrefix + replacements.size() + "END";
            replacements.add(formulaHtml(formula, bareParentheses.group().replace(pipeMarker,"|"), fontSize, false, dark, mathWidth));
            bareParentheses.appendReplacement(groupedMath, Matcher.quoteReplacement(marker));
        }
        bareParentheses.appendTail(groupedMath);
        String tokenMath = restoreUndelimitedMathTokens(groupedMath.toString(), mathPrefix,
            replacements, fontSize, dark, mathWidth, pipeMarker);
        // Explicit math and code are markers now, so repair only undelimited prose math.
        Matcher bareMath = BARE_MATH.matcher(tokenMath);
        StringBuffer repairedMath = new StringBuffer();
        while (bareMath.find()) {
            String formula = bareMath.group(1).replace(pipeMarker,"|");
            String marker = mathPrefix + replacements.size() + "END";
            replacements.add(formulaHtml(formula, formula, fontSize, false, dark, mathWidth));
            bareMath.appendReplacement(repairedMath, Matcher.quoteReplacement(marker));
        }
        bareMath.appendTail(repairedMath);
        String restored = repairedMath.toString();
        for (int i = 0; i < codeSources.size(); i++)
            restored = restored.replace(codePrefix + i + "END", codeSources.get(i));
        Node document = PARSER.parse(restored);
        removeExternalMedia(document);
        String result = HTML.render(document).replace("<table>",
            "<table border='1' cellspacing='0' cellpadding='7' width='100%'>");
        // CommonMark can leave bold markers literal when Hangul directly follows the closing marker.
        Matcher codeHtml = CODE_HTML.matcher(result);
        StringBuilder repaired = new StringBuilder();
        int offset = 0;
        while (codeHtml.find()) {
            repaired.append(repairBold(result.substring(offset, codeHtml.start()))).append(codeHtml.group());
            offset = codeHtml.end();
        }
        result = repaired.append(repairBold(result.substring(offset))).toString();
        for (int i = 0; i < replacements.size(); i++)
            result = result.replace(mathPrefix + i + "END", replacements.get(i));
        return result.replace(pipeMarker,"|");
    }

    private static String protectTablePipes(String markdown,String marker) {
        if(!markdown.contains("\\|"))return markdown;
        List<int[]> ranges=new ArrayList<>();
        collectTableLines(PARSER.parse(markdown),ranges);
        ranges.sort((a,b)->Integer.compare(a[0],b[0]));
        for(int i=ranges.size()-1;i>=0;i--) {
            int[] range=ranges.get(i);
            String source=markdown.substring(range[0],range[1]);
            markdown=markdown.substring(0,range[0])+source.replace("\\|",marker)+markdown.substring(range[1]);
        }
        return markdown;
    }

    private static void collectTableLines(Node node,List<int[]> ranges) {
        if(node instanceof TableBlock) {
            for(SourceSpan span:node.getSourceSpans())
                ranges.add(new int[]{span.getInputIndex(),span.getInputIndex()+span.getLength()});
            return;
        }
        for(Node child=node.getFirstChild();child!=null;child=child.getNext())collectTableLines(child,ranges);
    }

    /** Quote continuation markers are Markdown structure, not LaTeX comparison operators. */
    private static String quotedFormula(String formula,String markdown,int start) {
        int line=markdown.lastIndexOf('\n',start-1)+1;
        String prefix=markdown.substring(line,start);
        if(!prefix.matches("(?:[ \\t]*>[ \\t]*)+"))return formula;
        int depth=(int)prefix.chars().filter(ch->ch=='>').count();
        return formula.replaceAll("(?m)^[ \\t]*(?:>[ \\t]*){"+depth+"}","");
    }

    private static String breakLongProseParagraphs(String markdown) {
        Node document = PARSER.parse(markdown);
        List<int[]> ranges = new ArrayList<>();
        List<String> replacements = new ArrayList<>();
        for (Node node = document.getFirstChild(); node != null; node = node.getNext()) {
            if (!(node instanceof Paragraph) || node.getSourceSpans().isEmpty()) continue;
            List<SourceSpan> spans = node.getSourceSpans();
            int start = spans.getFirst().getInputIndex();
            SourceSpan last = spans.getLast();
            int end = last.getInputIndex() + last.getLength();
            String source = markdown.substring(start, end);
            if (source.length() < 150 || source.indexOf('\n') >= 0) continue;
            String spaced = splitLongParagraph(source);
            if (!spaced.equals(source)) {
                ranges.add(new int[]{start, end});
                replacements.add(spaced);
            }
        }
        for (int i = ranges.size() - 1; i >= 0; i--) {
            int[] range = ranges.get(i);
            markdown = markdown.substring(0, range[0]) + replacements.get(i) + markdown.substring(range[1]);
        }
        return markdown;
    }

    private static String splitLongParagraph(String source) {
        Matcher matcher = KOREAN_SENTENCE_BREAK.matcher(source);
        List<String> sentences = new ArrayList<>();
        int start = 0;
        while (matcher.find()) {
            sentences.add(source.substring(start, matcher.start() + 1).strip());
            start = matcher.end();
        }
        sentences.add(source.substring(start).strip());
        if (sentences.size() < 2) return source;
        StringBuilder result = new StringBuilder();
        StringBuilder paragraph = new StringBuilder();
        for (String sentence : sentences) {
            if (paragraph.length() >= 55 && paragraph.length() + 1 + sentence.length() > 145) {
                if (!result.isEmpty()) result.append("\n\n");
                result.append(paragraph);
                paragraph.setLength(0);
            }
            if (!paragraph.isEmpty()) paragraph.append(' ');
            paragraph.append(sentence);
        }
        if (!paragraph.isEmpty()) {
            if (!result.isEmpty()) result.append("\n\n");
            result.append(paragraph);
        }
        return result.toString();
    }

    private static String restoreBracketedMath(String markdown) {
        Matcher intervals = BRACKETED_INTERVAL.matcher(markdown);
        StringBuffer withIntervals = new StringBuffer();
        while (intervals.find()) {
            boolean escaped = intervals.start() > 0 && (markdown.charAt(intervals.start() - 1) == '\\'
                || markdown.charAt(intervals.start() - 1) == '!');
            String replacement = escaped ? intervals.group() : "\\(" + intervals.group() + "\\)";
            intervals.appendReplacement(withIntervals, Matcher.quoteReplacement(replacement));
        }
        intervals.appendTail(withIntervals);
        Matcher bracketed = BRACKETED_MATH.matcher(withIntervals.toString());
        StringBuffer repaired = new StringBuffer();
        while (bracketed.find()) {
            String formula = bracketed.group(1);
            boolean escaped = bracketed.start() > 0 && (withIntervals.charAt(bracketed.start() - 1) == '\\'
                || withIntervals.charAt(bracketed.start() - 1) == '!');
            boolean markdownLink = bracketed.end() < withIntervals.length()
                && withIntervals.charAt(bracketed.end()) == '(';
            // A citation or Markdown label is not automatically a formula.
            boolean mathematical = formula.matches(".*\\\\[A-Za-z]+.*")
                || formula.matches(".*[=^_<>].*");
            String replacement = !escaped && !markdownLink && mathematical && !formula.matches(".*[가-힣].*")
                ? "\\(" + formula + "\\)" : bracketed.group();
            bracketed.appendReplacement(repaired, Matcher.quoteReplacement(replacement));
        }
        bracketed.appendTail(repaired);
        return repaired.toString();
    }

    private static String restoreBracketedMathOutsideExplicit(String markdown) {
        Matcher matcher=MATH.matcher(markdown);
        StringBuffer protectedText=new StringBuffer();
        List<String> explicit=new ArrayList<>();
        String prefix="SYNESISEXPLICIT"+UUID.randomUUID().toString().replace("-", "")+"N";
        while(matcher.find()) {
            String marker=prefix+explicit.size()+"END";
            explicit.add(matcher.group());
            matcher.appendReplacement(protectedText,Matcher.quoteReplacement(marker));
        }
        matcher.appendTail(protectedText);
        String restored=restoreBracketedMath(protectedText.toString());
        for(int i=0;i<explicit.size();i++)restored=restored.replace(prefix+i+"END",explicit.get(i));
        return restored;
    }

    /** Saved model responses can contain two or more escape layers around TeX. */
    private static String normalizeDoubleEscapedMath(String markdown) {
        // Find the delimiters first; command repair stays inside recognised math.
        markdown = collapseMathBackslashes(markdown, false);
        Matcher matcher = MATH.matcher(markdown);
        StringBuffer repaired = new StringBuffer();
        while (matcher.find()) {
            String math = collapseMathBackslashes(matcher.group(), true);
            matcher.appendReplacement(repaired, Matcher.quoteReplacement(math));
        }
        matcher.appendTail(repaired);
        return repaired.toString();
    }

    private static String collapseMathBackslashes(String value, boolean commands) {
        StringBuilder result=new StringBuilder(value.length());
        for(int index=0;index<value.length();) {
            if(value.charAt(index)!='\\') {result.append(value.charAt(index++));continue;}
            int end=index+1;
            while(end<value.length() && value.charAt(end)=='\\')end++;
            int count=end-index;
            char next=end<value.length()?value.charAt(end):'\0';
            boolean delimiter=next=='(' || next==')';
            boolean command=commands && (Character.isLetter(next) || next==',' || next==';' || next==':');
            // Inside a matrix, \\x_2 is a row break followed by x_2, not an
            // escaped TeX command. Keep its two slashes before normalizing the
            // genuinely doubled commands elsewhere in the same formula.
            boolean matrixRow=commands && count>=2 && insideMatrix(value,index)
                && (count>=3 || Character.isLetter(next) && !knownMatrixCommand(value,end));
            int output=count>1 && (delimiter || command) && !matrixRow?1:count;
            result.append("\\".repeat(output));
            index=end;
        }
        return result.toString();
    }

    private static final Pattern MATRIX_ENVIRONMENT = Pattern.compile(
        "(?s)\\\\begin\\{([bBpPvV]?matrix)\\}.*?\\\\end\\{\\1\\}");
    private static final java.util.Set<String> MATRIX_COMMANDS = java.util.Set.of(
        "alpha","beta","gamma","delta","theta","pi","sin","cos","tan",
        "frac","dfrac","tfrac","sqrt","mathbf","mathrm","mathcal","text","left","right",
        "cdot","times","sum","int","begin","end","lvert","rvert","infty");

    private static boolean insideMatrix(String value,int index) {
        Matcher matrix=MATRIX_ENVIRONMENT.matcher(value);
        while(matrix.find())if(matrix.start()<index && index<matrix.end())return true;
        return false;
    }

    private static boolean knownMatrixCommand(String value,int start) {
        int end=start;
        while(end<value.length() && Character.isLetter(value.charAt(end)))end++;
        return MATRIX_COMMANDS.contains(value.substring(start,end));
    }

    // A model response may contain a JSON escape such as \r inside TeX's \right.
    // After JSON decoding that becomes a control character followed by "ight".
    // Repair unambiguous command fragments only inside explicit math, never in prose or code.
    private static String repairJsonEscapedMathCommands(String markdown) {
        Matcher matcher = MATH.matcher(markdown);
        StringBuffer repaired = new StringBuffer();
        while (matcher.find()) {
            String math = matcher.group()
                .replace("\r" + "ight", "\\right")
                .replace("\f" + "rac", "\\frac")
                .replace("\b" + "eta", "\\beta")
                .replace("\b" + "egin", "\\begin")
                .replace("\t" + "heta", "\\theta")
                .replace("\t" + "imes", "\\times")
                .replace("\t" + "ext", "\\text")
                .replace("\t" + "o", "\\to");
            matcher.appendReplacement(repaired, Matcher.quoteReplacement(math));
        }
        matcher.appendTail(repaired);
        return repaired.toString();
    }

    static String withoutControlChars(String value) {
        value = stripAnsiSequences(value);
        StringBuilder clean = new StringBuilder(value.length());
        for (int i = 0; i < value.length(); i++) {
            char character = value.charAt(i);
            if (!Character.isISOControl(character) || character == '\n' || character == '\r' || character == '\t')
                clean.append(character);
        }
        return clean.toString();
    }

    private static String stripAnsiSequences(String value) {
        // Some saved JSON contains the six literal characters "\\u001b" before a math closer.
        value = LITERAL_ESC_CLOSER.matcher(value).replaceAll(Matcher.quoteReplacement("\\"));
        return ORPHAN_ANSI_SGR.matcher(ANSI_CSI.matcher(value).replaceAll("")).replaceAll("");
    }

    private static String restoreUndelimitedMathTokens(String source, String mathPrefix,
            List<String> replacements, int fontSize, boolean dark, int mathWidth,String pipeMarker) {
        Matcher markers = OPAQUE_MARKER.matcher(source);
        StringBuilder result = new StringBuilder();
        int start = 0;
        while (markers.find()) {
            result.append(repairMathTokensInSegment(source.substring(start, markers.start()), mathPrefix,
                replacements, fontSize, dark, mathWidth,pipeMarker));
            result.append(markers.group());
            start = markers.end();
        }
        result.append(repairMathTokensInSegment(source.substring(start), mathPrefix,
            replacements, fontSize, dark, mathWidth,pipeMarker));
        return result.toString();
    }

    private static String repairMathTokensInSegment(String source, String mathPrefix,
            List<String> replacements, int fontSize, boolean dark, int mathWidth,String pipeMarker) {
        Matcher matcher = UNDELIMITED_MATH_TOKEN.matcher(source);
        StringBuffer repaired = new StringBuffer();
        while (matcher.find()) {
            String token = matcher.group();
            if (!(MATH_COMMAND.matcher(token).find() || token.contains("^{") || UNICODE_MATH.matcher(token).find())) {
                matcher.appendReplacement(repaired, Matcher.quoteReplacement(token));
                continue;
            }
            int end = token.length();
            while (end > 0 && "=+*/,.".indexOf(token.charAt(end - 1)) >= 0) end--;
            if (end == 0) {
                matcher.appendReplacement(repaired, Matcher.quoteReplacement(token));
                continue;
            }
            String suffix = token.substring(end);
            token = token.substring(0, end).replace(pipeMarker,"|");
            String marker = mathPrefix + replacements.size() + "END";
            replacements.add(formulaHtml(token, token, fontSize, false, dark, mathWidth));
            matcher.appendReplacement(repaired, Matcher.quoteReplacement(marker + suffix));
        }
        matcher.appendTail(repaired);
        return UndelimitedStudyMath.restore(repaired.toString(), (formula, original) -> {
            String marker = mathPrefix + replacements.size() + "END";
            replacements.add(formulaHtml(formula, original, fontSize, false, dark, mathWidth));
            return marker;
        });
    }

    /** Old tutor replies sometimes replace only the inline closing delimiter with NUL. */
    private static String restoreDamagedInlineClosers(String value) {
        Pattern damaged = Pattern.compile("\\\\\\(([^\\n\\r]{1,500}?)(?:\\\\u0000|\\x00)");
        Matcher matcher = damaged.matcher(value);
        StringBuffer result = new StringBuffer();
        while (matcher.find()) {
            String formula = matcher.group(1);
            // Never span a complete formula or steal a following formula's closing marker.
            boolean nested = formula.contains("\\(") || formula.contains("\\)")
                || formula.contains("\\[") || formula.contains("\\]") || formula.contains("$$");
            String replacement = !nested && (formula.contains("=") || formula.contains("\\"))
                ? "\\(" + formula + "\\)" : matcher.group();
            matcher.appendReplacement(result, Matcher.quoteReplacement(replacement));
        }
        matcher.appendTail(result);
        return result.toString();
    }

    private static String restoreControlMath(String value) {
        StringBuilder restored = new StringBuilder(value.length());
        for (int index = 0; index < value.length();) {
            char marker = value.charAt(index);
            if (marker == 0x1b || marker == 0x1c || marker == 0x1d) {
                int closing = value.indexOf(marker, index + 1);
                if (closing > index + 1 && closing - index <= 502) {
                    String formula = value.substring(index + 1, closing).strip();
                    if (looksLikeControlMath(formula)) {
                        if ((formula.startsWith("\\(") && formula.endsWith("\\)"))
                                || (formula.startsWith("\\[") && formula.endsWith("\\]"))
                                || (formula.startsWith("$$") && formula.endsWith("$$")))
                            restored.append(formula);
                        else restored.append("\\(").append(formula).append("\\)");
                        index = closing + 1;
                        continue;
                    }
                }
            }
            restored.append(marker);
            index++;
        }
        return restored.toString();
    }

    private static boolean looksLikeControlMath(String value) {
        if (value.isBlank() || value.length() > 500) return false;
        for (int index = 0; index < value.length(); index++) {
            char character = value.charAt(index);
            if (character >= '가' && character <= '힣') return false;
            if (Character.isLetterOrDigit(character) || "\\{}()[]^_+-=*/.,;| \t".indexOf(character) >= 0)
                continue;
            return false;
        }
        return true;
    }

    private static String repairBold(String html) {
        return html.replaceAll("\\*\\*([^*<>\\n]{2,80})\\*\\*", "<strong>$1</strong>");
    }

    static String linkProseReference(String html, String marker, String url) {
        if (!url.startsWith("https://") && !url.startsWith("http://")) return html;
        String link = "<a href='"+escape(url)+"'>"+escape(marker)+"</a>";
        Matcher protectedHtml = PROTECTED_HTML.matcher(html);
        StringBuilder result = new StringBuilder();
        int offset = 0;
        while (protectedHtml.find()) {
            result.append(html.substring(offset, protectedHtml.start()).replace(marker, link)).append(protectedHtml.group());
            offset = protectedHtml.end();
        }
        return result.append(html.substring(offset).replace(marker, link)).toString();
    }

    private static void collectCodeRanges(Node node, List<int[]> ranges) {
        if (node instanceof Code || node instanceof FencedCodeBlock || node instanceof IndentedCodeBlock) {
            List<SourceSpan> spans = node.getSourceSpans();
            if (!spans.isEmpty()) {
                SourceSpan first = spans.getFirst(), last = spans.getLast();
                ranges.add(new int[]{first.getInputIndex(), last.getInputIndex()+last.getLength()});
            }
            return;
        }
        for (Node child = node.getFirstChild(); child != null; child = child.getNext()) collectCodeRanges(child, ranges);
    }

    private static boolean isInlineFormula(String value) {
        if (value == null || value.isBlank() || value.matches(".*[가-힣].*")) return false;
        String trimmed = value.strip();
        if (trimmed.matches("[0-9][0-9,.]*")) return false; // $100 is money, not math.
        if (trimmed.matches("[0-9][0-9,.]*\\s+.*") && !trimmed.matches(".*[=+*/^_\\\\{}()].*")) return false;
        return !trimmed.matches(".*\\s+[A-Za-z]{3,}\\s+.*") || trimmed.matches(".*[=+*/^_\\\\{}()].*");
    }

    private static void removeExternalMedia(Node parent) {
        for (Node child = parent.getFirstChild(); child != null; ) {
            Node next = child.getNext();
            removeExternalMedia(child);
            if (child instanceof Link || child instanceof Image) {
                for (Node content = child.getFirstChild(); content != null; ) {
                    Node following = content.getNext();
                    content.unlink();
                    child.insertBefore(content);
                    content = following;
                }
                child.unlink();
            }
            child = next;
        }
    }

    private static String formulaHtml(String formula, String original, int fontSize, boolean display, boolean dark,
                                      int mathWidth) {
        if (formula == null || formula.length() > 2000 || UNSAFE_TEX.matcher(formula).find()) return escape(original);
        if (!display) {
            String measurement = StudyMeasurementText.inline(formula);
            if (measurement != null) return measurement;
        }
        try {
            String typeset = stackedFractions(normalizeFormula(formula.strip().replace('\n', ' ')));
            if (mathWidth != 0) {
                FormulaKey key=new FormulaKey(typeset,fontSize,display,dark);
                FormulaLayout layout;
                synchronized(FORMULA_LAYOUTS) {layout=FORMULA_LAYOUTS.get(key);}
                if(layout==null) {
                    TeXIcon icon = new TeXFormula(typeset).createTeXIcon(
                        display ? TeXConstants.STYLE_DISPLAY : TeXConstants.STYLE_TEXT,
                        (fontSize + 1) * (display ? 1.20f : 1.28f));
                    String id=UUID.nameUUIDFromBytes((typeset+"|"+fontSize+"|"+display+"|"+dark)
                        .getBytes(java.nio.charset.StandardCharsets.UTF_8)).toString().replace("-", "");
                    layout=new FormulaLayout(StudyMathMl.html(typeset,fontSize,display,dark),id,
                        new ScrollableMath(StudyMathMl.html(typeset,fontSize,false,dark),
                            icon.getIconWidth()+18,icon.getIconHeight()+16),icon.getIconWidth());
                    synchronized(FORMULA_LAYOUTS) {FORMULA_LAYOUTS.put(key,layout);}
                }
                if (layout.width() > (mathWidth > 0 ? mathWidth : display ? 540 : 240)) {
                    synchronized (SCROLLABLE_MATH) {
                        // The scroll row supplies its own block layout around selectable text.
                        SCROLLABLE_MATH.put(layout.id(),layout.scroll());
                    }
                    return "<br><!--MATHSCROLL:" + layout.id() + "--><br>";
                }
                return layout.html();
            }
            return StudyMathMl.html(typeset, fontSize, display, dark);
        } catch (Exception | LinkageError error) {
            return escape(original);
        }
    }

    static String stackedFractions(String formula) {
        if (!formula.contains("/") || formula.contains("\\text{")) return formula;
        Matcher division = SIMPLE_DIVISION.matcher(formula);
        StringBuffer converted = new StringBuffer();
        while (division.find()) {
            division.appendReplacement(converted, Matcher.quoteReplacement(
                "\\frac{" + division.group(1) + "}{" + division.group(2) + "}"));
        }
        division.appendTail(converted);
        return converted.toString();
    }

    /** Typography only: never infer a bound, exponent, sign or missing symbol. */
    private static String restoreSplitIntegral(String source) {
        // A premature closer directly after an integral leaves its written
        // lower/upper bounds outside math. Recover only this explicit shape;
        // never infer a bound from surrounding prose or cross a line/code fence.
        Pattern split=Pattern.compile("\\\\\\(([^\\n가-힣]{1,160}?(?:∫|\\\\int))\\\\\\)"
            +"([\\x{1D400}-\\x{1D7FF}ₐₑₒₓₕₖₗₘₙₚₛₜ])([⁰¹²³⁴⁵⁶⁷⁸⁹ⁿⁱᵃᵇᶜᵈ]+)"
            +"([ \\t]+[A-Za-z0-9(){}+*/=^_. ,−-]{1,160}?d[xyzt])(?![A-Za-z])");
        Matcher matcher=split.matcher(source);StringBuffer repaired=new StringBuffer();
        while(matcher.find()) {
            String lower=java.text.Normalizer.normalize(matcher.group(2),java.text.Normalizer.Form.NFKC);
            String upper=java.text.Normalizer.normalize(matcher.group(3),java.text.Normalizer.Form.NFKC);
            matcher.appendReplacement(repaired,Matcher.quoteReplacement("\\("+matcher.group(1)
                +"_{"+lower+"}^{"+upper+"}"+matcher.group(4)+"\\)"));
        }
        matcher.appendTail(repaired);return repaired.toString();
    }

    static String normalizeFormula(String formula) {
        formula=StudyUnicodeMath.normalize(formula);
        formula=Pattern.compile("√\\(([^()]*)\\)").matcher(formula).replaceAll("\\\\sqrt{($1)}");
        formula = normalizeScript(formula, "⁰¹²³⁴⁵⁶⁷⁸⁹ⁿⁱᵃᵇᶜᵈ⁺⁻⁽⁾", "0123456789niabcd+-()", "^");
        formula = normalizeScript(formula, "₀₁₂₃₄₅₆₇₈₉₊₋₍₎ₐₑₒₓₕₖₗₘₙₚₛₜᵢⱼᵣᵤᵥ", "0123456789+-()aeoxhklmnpstijruv", "_");
        String[] glyphs = {"∫","∑","√","∞","π","Δ","α","β","γ","θ","λ","μ","ρ","σ","ω","≈","≤","≥","×","·","−","\\lvert","\\rvert"};
        String[] commands = {"\\int ","\\sum ","\\sqrt ","\\infty ","\\pi ","\\Delta ","\\alpha ","\\beta ","\\gamma ","\\theta ","\\lambda ","\\mu ","\\rho ","\\sigma ","\\omega ","\\approx ","\\leq ","\\geq ","\\times ","\\cdot ","-","|","|"};
        for (int i=0;i<glyphs.length;i++) formula=formula.replace(glyphs[i],commands[i]);
        return formula;
    }

    private static String repairDisplayMathLayout(String formula) {
        // Repair layout escapes only inside a delimited display equation. Commands
        // such as \\nu, \\neq and \\nabla, and literal code, must remain unchanged.
        return formula.replaceAll("(?<!\\\\)\\\\[nr](?![A-Za-z])", "\n");
    }

    private static String normalizeScript(String formula, String symbols, String ascii, String operator) {
        Matcher matcher=Pattern.compile("["+symbols+"]+(?:\\.["+symbols+"]+)*").matcher(formula);
        StringBuffer result=new StringBuffer();
        while(matcher.find()) {
            StringBuilder value=new StringBuilder();
            for(char c:matcher.group().toCharArray()) value.append(c=='.'?'.':ascii.charAt(symbols.indexOf(c)));
            matcher.appendReplacement(result,Matcher.quoteReplacement(operator+"{"+value+"}"));
        }
        matcher.appendTail(result);
        return result.toString();
    }

    private static String escape(String value) {
        return value.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace("\"", "&quot;").replace("'", "&#39;");
    }
}

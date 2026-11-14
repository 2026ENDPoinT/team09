package dev.synesis.poc.pdf;

import java.util.Map;

/** Converts the supported study TeX notation into selectable MathML nodes. */
final class StudyMathMl {
    private static final Map<String, String> SYMBOLS = Map.ofEntries(
        Map.entry("alpha", "α"), Map.entry("beta", "β"), Map.entry("gamma", "γ"),
        Map.entry("delta", "δ"), Map.entry("Delta", "Δ"), Map.entry("epsilon", "ε"),
        Map.entry("varepsilon", "ε"), Map.entry("theta", "θ"), Map.entry("vartheta", "ϑ"),
        Map.entry("lambda", "λ"), Map.entry("mu", "μ"), Map.entry("nu", "ν"),
        Map.entry("pi", "π"), Map.entry("rho", "ρ"), Map.entry("sigma", "σ"),
        Map.entry("Sigma", "Σ"), Map.entry("tau", "τ"), Map.entry("phi", "φ"),
        Map.entry("varphi", "φ"), Map.entry("omega", "ω"), Map.entry("Omega", "Ω"),
        Map.entry("infty", "∞"), Map.entry("sum", "∑"), Map.entry("prod", "∏"),
        Map.entry("int", "∫"), Map.entry("oint", "∮"), Map.entry("partial", "∂"),
        Map.entry("nabla", "∇"), Map.entry("times", "×"), Map.entry("cdot", "·"),
        Map.entry("div", "÷"), Map.entry("pm", "±"), Map.entry("mp", "∓"),
        Map.entry("le", "≤"), Map.entry("leq", "≤"), Map.entry("ge", "≥"),
        Map.entry("geq", "≥"), Map.entry("neq", "≠"), Map.entry("approx", "≈"),
        Map.entry("equiv", "≡"), Map.entry("propto", "∝"), Map.entry("to", "→"),
        Map.entry("rightarrow", "→"), Map.entry("leftarrow", "←"),
        Map.entry("Rightarrow", "⇒"), Map.entry("Leftrightarrow", "⇔"),
        Map.entry("in", "∈"), Map.entry("notin", "∉"), Map.entry("subset", "⊂"),
        Map.entry("subseteq", "⊆"), Map.entry("cup", "∪"), Map.entry("cap", "∩"),
        Map.entry("forall", "∀"), Map.entry("exists", "∃"), Map.entry("ldots", "…"),
        Map.entry("cdots", "⋯"), Map.entry("lvert", "|"), Map.entry("rvert", "|"),
        Map.entry("langle", "⟨"), Map.entry("rangle", "⟩"), Map.entry("sin", "sin"),
        Map.entry("cos", "cos"), Map.entry("tan", "tan"), Map.entry("ln", "ln"),
        Map.entry("log", "log"), Map.entry("lim", "lim"), Map.entry("min", "min"),
        Map.entry("max", "max")
    );
    private static final String NS = "http://www.w3.org/1998/Math/MathML";

    private final String source;
    private int offset;

    private StudyMathMl(String source) { this.source = source; }

    static String html(String formula, int fontSize, boolean display, boolean dark) {
        String content = new StudyMathMl(formula).sequence('\0');
        int size = Math.max(fontSize + 1, Math.round(fontSize * (display ? 1.10f : 1.06f)));
        String math = "<math xmlns='" + NS + "' data-synesis-study-math='1' data-plain='"
            + escape(plainLabel(formula)) + "' display='" + (display ? "block" : "inline")
            + "' style='font-size:" + size + "pt;color:" + (dark ? "#f3f5f9" : "#182234")
            + "' aria-label='" + escape(formula) + "'>"
            + content + "</math>";
        return display
            ? "<span style='display:block;max-width:100%;overflow-x:auto;overflow-y:hidden'>" + math + "</span>"
            : "<span style='display:inline-block;max-width:100%;overflow-x:auto;vertical-align:middle'>"
                + math + "</span>";
    }

    /** Short readable fallback for Swing button labels, which cannot display MathML. */
    private static String plainLabel(String formula) {
        String result = formula.replaceAll("\\\\(?:left|right|,|;|:|!)", "");
        java.util.regex.Pattern fraction = java.util.regex.Pattern.compile(
            "\\\\(?:dfrac|tfrac|frac)\\{([^{}]+)\\}\\{([^{}]+)\\}");
        java.util.regex.Matcher matcher = fraction.matcher(result);
        StringBuffer flattened = new StringBuffer();
        while (matcher.find()) matcher.appendReplacement(flattened,
            java.util.regex.Matcher.quoteReplacement("(" + matcher.group(1) + ")/(" + matcher.group(2) + ")"));
        matcher.appendTail(flattened);
        result = flattened.toString().replaceAll(
            "\\\\(?:mathcal|mathbb|mathrm|mathbf|boldsymbol|operatorname|text)\\{([^{}]*)\\}", "$1");
        matcher = java.util.regex.Pattern.compile("\\\\([A-Za-z]+)").matcher(result);
        flattened = new StringBuffer();
        while (matcher.find()) matcher.appendReplacement(flattened,
            java.util.regex.Matcher.quoteReplacement(SYMBOLS.getOrDefault(matcher.group(1), matcher.group(1))));
        matcher.appendTail(flattened);
        return flattened.toString().replace("{", "").replace("}", "");
    }

    private String sequence(char end) {
        StringBuilder output = new StringBuilder("<mrow>");
        while (offset < source.length()) {
            if (end != '\0' && source.charAt(offset) == end) { offset++; break; }
            String base = atom();
            if (base.isEmpty()) continue;
            String sub = null, sup = null;
            while (offset < source.length()) {
                char marker = source.charAt(offset);
                if (marker != '_' && marker != '^') break;
                offset++;
                if (marker == '_') sub = argument();
                else sup = argument();
            }
            boolean limits = base.equals(tag("mo", "∑")) || base.equals(tag("mo", "∏"))
                || base.equals(tag("mi", "lim"));
            if (sub != null && sup != null) base = tag(limits ? "munderover" : "msubsup", base + sub + sup);
            else if (sub != null) base = tag("msub", base + sub);
            else if (sup != null) base = tag("msup", base + sup);
            output.append(base);
        }
        return output.append("</mrow>").toString();
    }

    private String atom() {
        if (offset >= source.length()) return "";
        char c = source.charAt(offset++);
        if (c == '{') return sequence('}');
        if (c == '}') return "";
        if (c == '\\') return command();
        if (Character.isWhitespace(c)) return "";
        if (Character.isDigit(c)) {
            int start = offset - 1;
            while (offset < source.length() && (Character.isDigit(source.charAt(offset))
                    || source.charAt(offset) == '.')) offset++;
            return tag("mn", escape(source.substring(start, offset)));
        }
        if (Character.isLetter(c) && c < 128) return tag("mi", escape(String.valueOf(c)));
        if ("αβγδεθλμπρσφωΔΣΩ".indexOf(c) >= 0) return tag("mi", escape(String.valueOf(c)));
        if (c == '&') return tag("mo", "&amp;");
        return tag("mo", escape(String.valueOf(c)));
    }

    private String argument() {
        skipSpaces();
        if (offset >= source.length()) return tag("mrow", "");
        if (source.charAt(offset) == '{') { offset++; return sequence('}'); }
        return atom();
    }

    private String command() {
        if (offset >= source.length()) return "";
        int start = offset;
        while (offset < source.length() && Character.isLetter(source.charAt(offset))) offset++;
        if (start == offset) {
            char c = source.charAt(offset++);
            if (c == '\\') return tag("mspace", "");
            if (c == ',' || c == ';' || c == ':' || c == ' ' || c == '!') return "";
            return tag("mo", escape(String.valueOf(c)));
        }
        String name = source.substring(start, offset);
        String symbol = SYMBOLS.get(name);
        if (symbol != null) return tag(name.length() > 2 && Character.isLetter(symbol.charAt(0)) ? "mi" : "mo", escape(symbol));
        return switch (name) {
            case "left", "right" -> "";
            case "frac", "dfrac", "tfrac" -> tag("mfrac", argument() + argument());
            case "sqrt" -> root();
            case "text", "mathrm", "operatorname" -> tag("mtext", plainArgument());
            case "mathbf", "boldsymbol" -> "<mstyle mathvariant='bold'>" + argument() + "</mstyle>";
            case "mathbb" -> "<mstyle mathvariant='double-struck'>" + argument() + "</mstyle>";
            case "mathcal" -> "<mstyle mathvariant='script'>" + argument() + "</mstyle>";
            case "vec", "overrightarrow" -> tag("mover", argument() + tag("mo", "→"));
            case "hat", "widehat" -> tag("mover", argument() + tag("mo", "^"));
            case "bar", "overline" -> tag("mover", argument() + tag("mo", "¯"));
            case "begin" -> environment();
            case "end" -> { plainArgument(); yield ""; }
            default -> tag("mtext", escape("\\" + name));
        };
    }

    private String root() {
        skipSpaces();
        String index = null;
        if (offset < source.length() && source.charAt(offset) == '[') {
            int start = ++offset;
            while (offset < source.length() && source.charAt(offset) != ']') offset++;
            index = new StudyMathMl(source.substring(start, offset)).sequence('\0');
            if (offset < source.length()) offset++;
        }
        String radicand = argument();
        return index == null ? tag("msqrt", radicand) : tag("mroot", radicand + index);
    }

    private String environment() {
        String name = rawArgument();
        String endToken = "\\end{" + name + "}";
        int end = source.indexOf(endToken, offset);
        if (end < 0) return tag("mtext", escape("\\begin{" + name + "}"));
        String content = source.substring(offset, end);
        offset = end + endToken.length();
        StringBuilder rows = new StringBuilder("<mtable>");
        for (String row : content.split(java.util.regex.Pattern.quote("\\\\"), -1)) {
            rows.append("<mtr>");
            for (String cell : row.split("&", -1))
                rows.append(tag("mtd", new StudyMathMl(cell.strip()).sequence('\0')));
            rows.append("</mtr>");
        }
        rows.append("</mtable>");
        return switch (name) {
            case "pmatrix" -> tag("mrow", tag("mo", "(") + rows + tag("mo", ")"));
            case "bmatrix" -> tag("mrow", tag("mo", "[") + rows + tag("mo", "]"));
            case "vmatrix" -> tag("mrow", tag("mo", "|") + rows + tag("mo", "|"));
            default -> rows.toString();
        };
    }

    private String plainArgument() { return escape(rawArgument()); }

    private String rawArgument() {
        skipSpaces();
        if (offset >= source.length()) return "";
        if (source.charAt(offset) != '{') return String.valueOf(source.charAt(offset++));
        offset++;
        int start = offset, depth = 1;
        while (offset < source.length() && depth > 0) {
            char c = source.charAt(offset++);
            if (c == '{') depth++;
            else if (c == '}') depth--;
        }
        return source.substring(start, Math.max(start, offset - 1));
    }

    private void skipSpaces() {
        while (offset < source.length() && Character.isWhitespace(source.charAt(offset))) offset++;
    }

    private static String tag(String name, String content) { return "<" + name + ">" + content + "</" + name + ">"; }

    private static String escape(String value) {
        return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("\"", "&quot;").replace("'", "&#39;");
    }
}

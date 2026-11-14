package dev.synesis.poc.pdf;

import java.util.regex.Pattern;

/** Offline source-table checks: no JFrame, PDF, credentials, or provider. */
public final class StudyMarkdownTableCellsTest {
    public static void main(String[] args) {
        String longCell="이 셀은 원문에서 읽을 수 있는 모든 조건과 설명을 유지해요. ".repeat(8);
        String table=table(new String[][]{{"긴 셀",longCell},{"다음 행","끝까지 보존해요."}});
        String html=StudyMarkdown.render(table,18);
        require(html.contains(longCell.strip()),"cell longer than 120 characters remains complete");
        require(count(html,"<td>")==4 && count(html,"<tr>")==3,"long table remains rectangular");
        for(String formula:new String[]{"\\(|r|<1\\)","\\(\\|r\\|<1\\)","\\(P(A|B)\\)",
                "\\(\\left|x\\right|\\)","\\(\\frac{a|b}{c}\\)","$|r|<1$"}) {
            String outside=math(StudyMarkdown.render(formula,18));
            String inside=StudyMarkdown.render(table(new String[][]{{"식",formula},{"끝","보존"}}),18);
            require(!outside.isEmpty() && math(inside).equals(outside),
                "table pipe escaping preserves the original rendered formula: "+formula+" => "+inside);
            require(count(inside,"<td>")==4 && count(inside,"<tr>")==3,"math pipe does not create a column");
            require(!inside.contains("SYNESISTABLEPIPE"),"temporary markers never leak");
        }
        for(String code:new String[]{"`left | right`","`flags |= mask`","`a || b`", "`r\"\\|\"`",
                "`` `a|b` ``", "`print(\"$x$ **bold** | \\(x\\)\")`"}) {
            String outside=code(StudyMarkdown.render(code,18));
            String inside=StudyMarkdown.render(table(new String[][]{{"코드",code},{"끝","보존"}}),18);
            require(!outside.isEmpty() && code(inside).equals(outside),"source code pipes remain literal: "+inside);
            require(count(inside,"<td>")==4,"code pipes do not split the row");
            require(!inside.contains("synesis-study-math") && !inside.contains("SYNESISCODE"),"code does not become math");
        }
        String prose=StudyMarkdown.render("| 왼쪽\\|오른쪽 | 설명 |\n| --- | --- |\n| A\\|B | C |\n| D | E |",18);
        require(prose.contains("<th>왼쪽|오른쪽</th>") && prose.contains("<td>A|B</td>"),"header and prose pipes are literal");
        require(count(prose,"<th>")==2 && count(prose,"<td>")==4,"escaped header does not add a column");
        String plain=StudyMarkdown.render("표 밖의 \\(\\|r\\|\\)와 `a\\|b`를 보존해요.",18);
        require(plain.contains("aria-label='\\|r\\|'") && plain.contains("<code>a\\|b</code>"),"non-table backslashes are untouched");
        String fenced=StudyMarkdown.render("```text\n| A\\|B | C |\n| --- | --- |\n```",18);
        require(fenced.contains("A\\|B") && !fenced.contains("<table"),"fenced table-shaped source is still code");
        System.out.println("StudyMarkdownTableCellsTest OK");
    }

    private static String table(String[][] rows) {
        StringBuilder text=new StringBuilder("| 종류 | 내용 |\n| --- | --- |\n");
        for(String[] row:rows)text.append("| ").append(cell(row[0])).append(" | ").append(cell(row[1])).append(" |\n");
        return text.toString();
    }
    private static String cell(String value) {return value.replace("|","\\|");}
    private static String math(String html) {return match(html,"(?s)<math\\b[^>]*>.*?</math>");}
    private static String code(String html) {return match(html,"(?s)<code>.*?</code>");}
    private static String match(String html,String regex) {
        var found=Pattern.compile(regex).matcher(html);return found.find()?found.group():"";
    }
    private static int count(String text,String token) {return text.split(Pattern.quote(token),-1).length-1;}
    private static void require(boolean value,String message) {if(!value)throw new AssertionError(message);}
}

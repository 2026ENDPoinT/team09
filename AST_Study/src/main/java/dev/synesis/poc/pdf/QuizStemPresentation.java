package dev.synesis.poc.pdf;

import java.util.regex.Pattern;
import java.util.List;
import java.util.ArrayList;
import org.commonmark.node.Heading;
import org.commonmark.node.Text;
import org.commonmark.parser.IncludeSourceSpans;
import org.commonmark.parser.Parser;

/** Display-only paragraph boundaries; never changes the stored proposition or answer. */
final class QuizStemPresentation {
    private QuizStemPresentation() {}
    static final String OX_GUIDE="주어진 진술이 참이면 O, 거짓이면 X를 선택하세요.";
    static final String OX_PASSAGE_GUIDE="제시문을 읽은 뒤, 주어진 진술이 참이면 O, 거짓이면 X를 선택하세요.";
    private static final Parser PARSER=Parser.builder().includeSourceSpans(IncludeSourceSpans.BLOCKS).build();
    record Sections(String passage,String question) {}
    /** Only app-generated top-level headings are split; legacy prose remains intact. */
    static Sections sections(String source) {
        if(source==null)return new Sections("","");
        var root=PARSER.parse(source);
        var first=root.getFirstChild();
        if(!(first instanceof Heading heading)||heading.getLevel()!=3||heading.getSourceSpans().isEmpty()
                ||heading.getSourceSpans().getFirst().getInputIndex()!=0)return new Sections("",source);
        String title=heading.getFirstChild() instanceof Text text?text.getLiteral():"";
        int begin=afterHeading(source,heading);
        if(title.equals("문제")||title.equals("판단할 진술"))return new Sections("",source.substring(begin).strip());
        if(!title.equals("제시문"))return new Sections("",source);
        for(var node=heading.getNext();node!=null;node=node.getNext()){
            if(node instanceof Heading next&&next.getLevel()==3&&next.getFirstChild() instanceof Text text
                    &&(text.getLiteral().equals("문제")||text.getLiteral().equals("판단할 진술"))){
                int split=next.getSourceSpans().getFirst().getInputIndex();
                return new Sections(source.substring(begin,split).strip(),source.substring(afterHeading(source,next)).strip());
            }
        }
        return new Sections("",source);
    }
    private static int afterHeading(String source,Heading heading){
        int start=heading.getSourceSpans().getFirst().getInputIndex(),end=source.indexOf('\n',start);
        return end<0?source.length():end+1;
    }
    private static final Pattern OPTION_LINE=Pattern.compile("(?m)^\\h*(?:[①②③④]\\h*|[1-4A-D][.)]\\h+)");
    /** Align a duplicated, complete option list only when all four texts match exactly. */
    static String alignOptions(String source,List<QuizQuestion.Option> options){
        if(options.size()!=4)return source;
        var starts=new ArrayList<Integer>();var ends=new ArrayList<Integer>();
        var labels=OPTION_LINE.matcher(source);
        while(labels.find()){
            boolean protectedLabel=false;var protectedText=PROTECTED.matcher(source);
            while(protectedText.find())if(protectedText.start()<=labels.start()&&labels.start()<protectedText.end()){
                protectedLabel=true;break;
            }
            if(!protectedLabel){starts.add(labels.start());ends.add(labels.end());}
        }
        if(starts.size()!=4)return source;
        var texts=options.stream().map(option->normalizedOption(option.text())).toList();
        if(new java.util.HashSet<>(texts).size()!=4)return source;
        var found=new java.util.HashSet<String>();
        for(int i=0;i<4;i++){
            String text=normalizedOption(source.substring(ends.get(i),i<3?starts.get(i+1):source.length()));
            if(!texts.contains(text)||!found.add(text))return source;
        }
        var result=new StringBuilder(source.substring(0,starts.getFirst()));
        for(int i=0;i<4;i++){
            if(i>0)result.append('\n');
            result.append(new String[]{"①","②","③","④"}[i]).append(' ').append(options.get(i).text());
        }
        return result.toString();
    }
    private static String normalizedOption(String value){return value.strip().replaceAll("[\\s\\u00a0]+","");}
    private static final Pattern PROTECTED = Pattern.compile(
        "(?s)```.*?(?:```|\\z)|~~~.*?(?:~~~|\\z)|`[^`]*`|\\$\\$.*?\\$\\$|\\$[^\\n$]*\\$|\\\\\\(.*?\\\\\\)|\\\\\\[.*?\\\\\\]");
    private static final Pattern GUIDE = Pattern.compile(
        "(?:(?:다음|아래|위의|제시된)\\h+(?:설명|명제|문장|내용)(?:이|가)\\h+)?"
        + "(?:옳으면|맞으면|참이면)\\h*[OoＯ○](?:를)?\\h*[,，]\\h*"
        + "(?:틀리면|거짓이면)\\h*[XxＸ×](?:를)?\\h*"
        + "(?:쓰시오|고르시오|선택하시오|표시하시오|답하시오|고르세요|선택하세요|표시하세요|쓰세요)"
        + "(?:[.:：。]|(?=\\R|$))");

    static String ox(String source) {
        if (source == null || source.isEmpty()) return source;
        var result = new StringBuilder();
        var protectedText = PROTECTED.matcher(source);
        int cursor = 0;
        while (protectedText.find()) {
            result.append(paragraphs(source.substring(cursor, protectedText.start())));
            result.append(protectedText.group());
            cursor = protectedText.end();
        }
        result.append(paragraphs(source.substring(cursor)));
        return result.toString();
    }

    private static String paragraphs(String text) {
        var matches = GUIDE.matcher(text);
        var out = new StringBuilder();
        int cursor = 0;
        while (matches.find()) {
            // Only complete instruction sentences at a sentence/paragraph boundary.
            String before = text.substring(0, matches.start());
            String trimmed = before.stripTrailing();
            boolean boundary = trimmed.isEmpty() || trimmed.matches("(?s).*[.!?。:：]$")
                || before.substring(trimmed.length()).contains("\n");
            if (!boundary) continue;
            String gap = text.substring(cursor, matches.start());
            out.append(gap.stripTrailing());
            if (out.length() > 0 || !gap.isEmpty()) out.append("\n\n");
            out.append(matches.group());
            cursor = matches.end();
            int next = cursor;
            while (next < text.length() && Character.isWhitespace(text.charAt(next))) next++;
            if (next < text.length() || next > cursor) out.append("\n\n");
            cursor = next;
        }
        out.append(text.substring(cursor));
        return out.toString();
    }
}

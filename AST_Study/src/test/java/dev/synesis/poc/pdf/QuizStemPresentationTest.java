package dev.synesis.poc.pdf;

public final class QuizStemPresentationTest {
    public static void main(String[] args) throws Exception {
        String guide="다음 설명이 옳으면 O, 틀리면 X를 쓰시오.";
        eq(QuizStemPresentation.ox(guide+" 명제이다."),guide+"\n\n명제이다.");
        eq(QuizStemPresentation.ox("명제이다. 맞으면 O, 틀리면 X를 쓰시오."),"명제이다.\n\n맞으면 O, 틀리면 X를 쓰시오.");
        String middle="배경이다. 다음 명제가 맞으면 O, 틀리면 X를 쓰시오: 판단할 관계이다.";
        eq(QuizStemPresentation.ox(middle),"배경이다.\n\n다음 명제가 맞으면 O, 틀리면 X를 쓰시오:\n\n판단할 관계이다.");
        String code="```cpp\n// "+guide+"\nint O = 1;\n```";
        eq(QuizStemPresentation.ox(code),code);
        String math="$$ "+guide+" $$와 `"+guide+"`는 인용이다.";
        eq(QuizStemPresentation.ox(math),math);
        String normal="O/X라는 변수 표기를 비교하시오. '맞으면 O, 틀리면 X를 쓰시오.'라는 문자열이다.";
        eq(QuizStemPresentation.ox(normal),normal);
        for(String input:new String[]{guide+" 명제이다.",middle,guide+"\n\n"+code+"\n\n명제이다.",code+"\n"+guide}) {
            String display=QuizStemPresentation.ox(input);
            eq(QuizStemPresentation.ox(display),display);
            eq(display.replaceAll("\\s", ""),input.replaceAll("\\s", ""));
        }
        for(String path:args) {
            String original=java.nio.file.Files.readString(java.nio.file.Path.of(path));
            String display=QuizStemPresentation.ox(original);
            eq(display.replaceAll("\\s",""),original.replaceAll("\\s",""));
            eq(QuizStemPresentation.ox(display),display);
            if(!display.contains("\n\n"))throw new AssertionError("missing paragraph: "+path);
            System.out.println("--- "+path+" ---\n"+display);
        }
        System.out.println("QuizStemPresentationTest passed: front/back/middle, code/math protection, idempotence, non-whitespace preservation.");
    }
    private static void eq(String actual,String expected) {if(!actual.equals(expected))throw new AssertionError(actual+" != "+expected);}
}

package dev.synesis.poc.pdf;

public final class TutorTextRevealTest {
    public static void main(String[] args) {
        TutorTextReveal reveal=new TutorTextReveal();
        String answer="가😀나다 ".repeat(1000);
        reveal.accept(answer);
        String first=reveal.advance();
        if(first.isEmpty()||first.equals(answer))throw new AssertionError("burst displayed at once");
        int ticks=1;
        while(!reveal.complete()&&ticks++<100) {
            String part=reveal.advance();
            if(!answer.startsWith(part)||Character.isHighSurrogate(part.charAt(part.length()-1)))
                throw new AssertionError("broken text boundary");
        }
        if(!reveal.complete())throw new AssertionError("unbounded display delay");
        reveal.accept("고친 😀 답변");
        if(!reveal.advance().equals("고친 😀 답변"))throw new AssertionError("replacement lost");
        reveal.reset();reveal.accept("짧은 답변");reveal.advance();
        if(!reveal.complete())throw new AssertionError("short answer stalled");
        System.out.println("TutorTextRevealTest OK");
    }
}

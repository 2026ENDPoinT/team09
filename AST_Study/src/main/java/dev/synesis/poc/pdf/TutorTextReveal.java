package dev.synesis.poc.pdf;

/** Bounded display buffering for cached answers and bursty network chunks. */
final class TutorTextReveal {
    private String target="", shown="";
    private final int minimum,divisor;
    TutorTextReveal(){this(16,8);}
    TutorTextReveal(int minimum,int divisor){
        if(minimum<1||divisor<1)throw new IllegalArgumentException();
        this.minimum=minimum;this.divisor=divisor;
    }
    void reset(){target="";shown="";}
    void accept(String text){
        target=text;
        if(!target.startsWith(shown)) {
            int common=0,limit=Math.min(shown.length(),target.length());
            while(common<limit&&shown.charAt(common)==target.charAt(common))common++;
            if(common>0&&Character.isHighSurrogate(target.charAt(common-1)))common--;
            shown=target.substring(0,common);
        }
    }
    String advance(){
        int remaining=target.codePointCount(shown.length(),target.length());
        int count=Math.min(remaining,Math.max(minimum,(remaining+divisor-1)/divisor));
        shown=target.substring(0,target.offsetByCodePoints(shown.length(),count));
        return shown;
    }
    boolean complete(){return shown.equals(target);}
}

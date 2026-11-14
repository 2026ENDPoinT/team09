package dev.synesis.poc.pdf;

import java.text.Normalizer;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Typeset mathematical Unicode alphabets without relying on the prose font's coverage. */
final class StudyUnicodeMath {
    private static final Pattern TOKEN=Pattern.compile(
        "(?:[A-Za-z](?=[₀-₉ₐₑₒₓₕₖₗₘₙₚₛₜᵢⱼᵣᵤᵥ⁰¹²³⁴⁵⁶⁷⁸⁹ⁿⁱᵃᵇᶜᵈ])|[\\x{1D400}-\\x{1D7FF}ℂℊℋℌℍℎℐℑℒℓℕℙℚℛℜℝℤℬℭℯℰℱℳℴ])"
        +"(?:[\\x{1D400}-\\x{1D7FF}₀-₉ₐₑₒₓₕₖₗₘₙₚₛₜᵢⱼᵣᵤᵥ⁰¹²³⁴⁵⁶⁷⁸⁹ⁿⁱᵃᵇᶜᵈ⁺⁻⁽⁾₊₋₍₎]|[_^](?:\\{[^{}\\n]{1,40}\\}|[A-Za-z0-9]))*(?:\\*(?![A-Za-z0-9]))?");
    private StudyUnicodeMath() {}

    // Explicit math and code have already become opaque markers at this point.
    static String restore(String prose,java.util.function.BiFunction<String,String,String> render) {
        Matcher matcher=TOKEN.matcher(prose);StringBuffer result=new StringBuffer();
        while(matcher.find()) {
            String original=matcher.group();
            String formula=original.endsWith("*")?original.substring(0,original.length()-1)+"^{*}":original;
            matcher.appendReplacement(result,Matcher.quoteReplacement(render.apply(formula,original)));
        }
        matcher.appendTail(result);return result.toString();
    }

    static String normalize(String formula) {
        StringBuilder result=new StringBuilder();
        formula.codePoints().forEach(cp->{
            String original=new String(Character.toChars(cp)),name=Character.getName(cp);
            boolean mathematical=cp>=0x1d400&&cp<=0x1d7ff;
            boolean letterlike=cp>=0x2100&&cp<=0x214f&&name!=null
                &&(name.contains("SCRIPT")||name.contains("DOUBLE-STRUCK")||name.contains("BLACK-LETTER")||cp==0x210e);
            if(!mathematical&&!letterlike){result.append(original);return;}
            String plain=Normalizer.normalize(original,Normalizer.Form.NFKC);
            if(plain.equals(original)){result.append(original);return;}
            String command=name.contains("DOUBLE-STRUCK")?"mathbb":name.contains("SCRIPT")?"mathcal":
                name.contains("FRAKTUR")||name.contains("BLACK-LETTER")?"mathfrak":name.contains("MONOSPACE")?"mathtt":
                name.contains("BOLD")?name.contains("ITALIC")?"boldsymbol":"mathbf":
                name.contains("SANS-SERIF")?"mathsf":"mathit";
            result.append('\\').append(command).append('{').append(plain).append('}');
        });
        return result.toString();
    }
}

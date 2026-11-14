package dev.synesis.poc.pdf;

/** Screenshot regressions: unsupported styled variables and escaped quoted equations. */
public final class StudyMathTextRepairTest {
    public static void main(String[] args) {
        String sample=StudyMarkdown.renderWithScrollableMath("표본점 xᵢ*와 A(xᵢ*)Δx를 비교해요.",18);
        require(!sample.contains("ᵢ")&&sample.contains("_{i}")&&sample.contains("^{*}"),"plain indexed sample points use supported math glyphs");
        String integral=StudyMarkdown.renderWithScrollableMath("구간 [c,d]이면 \\\\(V=∫\\\\)𝑐ᵈ A(y)dy예요.",18);
        require(!integral.contains("𝑐")&&!integral.contains("ᵈ")&&integral.contains("_{c}^{d}"),"split integral preserves both bounds and differential");
        require(integral.contains("A(y)dy")&&integral.contains("예요"),"integrand is restored without consuming prose");
        String literal=StudyMarkdown.render("`xᵢ*`와 `\\(V=∫\\)𝑐ᵈ A(y)dy`",18);
        require(literal.contains("xᵢ*")&&literal.contains("𝑐ᵈ"),"literal code is not repaired");
        String prose=StudyMarkdown.renderWithScrollableMath("입력 𝒙는 특징을 담고, 각 가중치 𝑤ᵢ는 해당 특징 𝑥ᵢ가 기여하는 정도예요. 편향 𝑏를 더해요.",18);
        require(prose.contains("<math ")&&!prose.contains("𝑤")&&!prose.contains("𝑥")&&!prose.contains("ᵢ"),"styled variables use the equation renderer");
        require(prose.contains("mathit{w}_{i}")&&prose.contains("mathit{x}_{i}"),"indices and variable identities survive");
        String quote=StudyMarkdown.renderWithScrollableMath(
            "> $$\\n> \\text{이진 분류:}\\quad \\sigma(z)=\\frac{1}{1+e^{-z}}\\n> $$\n\n"
            +"> $$\\n> \\text{멀티클래스 분류:}\\quad \\phi(\\mathbf{z})_i=\\frac{e^{z_i}}{\\sum_{j=1}^{K}e^{z_j}}\\n> $$",18);
        require(quote.split("data-synesis-study-math",-1).length==3,"both quoted formulas render");
        require(!quote.contains("$$")&&!quote.contains("\\n&gt;"),"escaped layout does not leak into displayed prose");
        String explicit=StudyMarkdown.renderWithScrollableMath("\\(𝒙+𝑤ᵢ+ℝ\\)",18);
        require(explicit.contains("<math ")&&!explicit.contains("𝒙"),"explicit Unicode formulas also render");
        String comparison=StudyMarkdown.renderWithScrollableMath("$$a\n> b$$",18);
        require(comparison.contains("&gt;"),"a greater-than operator on a new line is not a quote marker");
        String escaped=StudyMarkdown.renderWithScrollableMath("$$\\n x+\\nu+\\nabla f\\n$$",18);
        require(escaped.contains("<math ")&&!escaped.contains("$$"),"literal layout newlines are repaired without consuming commands");
        String code=StudyMarkdown.render("`𝑤ᵢ`\n\n```text\n$$\\n> \\nu\n𝑥ᵢ\n```",18);
        require(code.contains("𝑤ᵢ")&&code.contains("𝑥ᵢ")&&code.contains("$$\\n&gt;"),"code remains literal");
        String ordinary=StudyMarkdown.renderWithScrollableMath("集合 \\(\\nu+\\nabla f+\\neq\\)\n\n価格 $100、変数 ABC。",18);
        require(ordinary.contains("\\nu")&&ordinary.contains("\\nabla")&&ordinary.contains("$100"),"commands and currency are preserved");
        String broken="경찰보다 45.0\\,\\mathrm{m} 앞서 있어요. "
            +"경찰은 \\(x_{경찰}=\\frac12(3.00)t^2\\u0000이고, "
            +"자동차는 \\(x_{자동차}=45.0+45.0t\\u0000예요. "
            +"정리하면 \\(t^2-30.0t-30.0=0\\u0000이에요.";
        String fixed=StudyMarkdown.renderWithScrollableMath(broken,18);
        require(!fixed.contains("u0000")&&!fixed.contains("\\("),"damaged inline closers do not leak");
        require(fixed.contains("앞서 있어요")&&fixed.contains("자동차는")&&fixed.contains("정리하면"),"prose between damaged formulas is preserved");
        require(fixed.split("data-synesis-study-math",-1).length==5,"unit and all three damaged inline formulas render");
        String nul=StudyMarkdown.renderWithScrollableMath("\\(x=1"+(char)0+"이에요.",18);
        require(nul.contains("<math ")&&nul.contains("이에요"),"decoded NUL closer also renders");
        String protectedCode=StudyMarkdown.render("`\\(x=1\\u0000`와 `45\\,\\mathrm{m}`",18);
        require(protectedCode.contains("u0000")&&protectedCode.contains("\\mathrm"),"code examples stay literal");
        System.out.println("StudyMathTextRepairTest passed");
    }
    private static void require(boolean ok,String message){if(!ok)throw new AssertionError(message);}
}

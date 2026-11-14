package dev.synesis.poc.pdf;

import javax.imageio.ImageIO;
import javax.swing.JButton;
import javax.swing.JEditorPane;
import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.image.BufferedImage;
import java.nio.file.Files;
import java.nio.file.Path;

/** Small offline check for the rendered study content; no PDF or API key needed. */
public final class StudyMarkdownTest {
    public static void main(String[] args) throws Exception {
        String unicodeMath="적분은 W=∫₀.₀₅⁰.⁰⁸800x예요. 반지름 r₂와 r₁, 식 \\(πr²\\)를 비교해요.";
        String unicodeHtml=StudyMarkdown.render(unicodeMath,18);
        require(unicodeHtml.split("synesis-study-math",-1).length==5,
            "Unicode calculus notation renders as equations: "+unicodeHtml);
        require(!withoutMath(unicodeHtml).matches("(?s).*[∫₀₂₁⁰⁸²].*"),
            "no raw Unicode scripts remain in prose");
        require(StudyMarkdown.normalizeFormula("∫₀.₀₅⁰.⁰⁸800x").equals("\\int _{0.05}^{0.08}800x"),
            "decimal bounds retain their exact values");
        require(StudyMarkdown.normalizeFormula("∫ₐᵇ").equals("\\int _{a}^{b}"),
            "letter bounds retain their exact symbols");
        String unicodeCode=StudyMarkdown.render("`r₂=πr²`와 C:\\π.txt, $100을 받아 $110을 갚아요.",18);
        require(unicodeCode.contains("<code>r₂=πr²</code>") && unicodeCode.contains("C:\\π.txt")
            && unicodeCode.contains("$100을 받아 $110을"),"code, path and currency are unchanged");
        String normalizedBars=StudyMarkdown.render("\\(\\lvert x\\rvert\\)",18);
        require(normalizedBars.contains("<math "),"absolute-value delimiters render");
        String matrixRows=StudyMarkdown.render("벡터 \\(\\mathbf{x}=\\begin{bmatrix}x_1\\\\x_2\\end{bmatrix}\\)예요.",18);
        require(matrixRows.contains("<mtable>") && !withoutMath(matrixRows).contains("bmatrix"),
            "matrix row separator remains doubled for the TeX renderer: "+matrixRows);
        String html = StudyMarkdown.render("## 핵심\n\n1. **정의**를 확인합니다.\n2. $E=mc^2$를 봅니다.\n\n"
            + "| 개념 | 설명 |\n| --- | --- |\n| A | B |\n\n$$\\frac{a}{b}$$", 13);
        require(html.contains("<h2>핵심</h2>"), "heading");
        require(html.contains("<ol>"), "numbered list");
        require(html.contains("<strong>정의</strong>"), "emphasis");
        require(html.contains("<table border='1'"), "table");
        require(html.contains("synesis-study-math") && html.contains("<mfrac>"), "selectable equation");
        String conceptTitle=PdfWorkspace.conceptTitleHtml("보상 함수 \\(\\mathcal{R}(f)\\)",false,18);
        String visibleConceptTitle=conceptTitle.replaceAll("<[^>]*>", "");
        require(conceptTitle.startsWith("<html>") && conceptTitle.contains("R(f)")
            && !visibleConceptTitle.contains("\\(") && !visibleConceptTitle.contains("\\mathcal"),
            "concept title renders inline math instead of showing TeX delimiters: "+conceptTitle);
        String expandedTitle=PdfWorkspace.conceptTitleHtml("입력 **데이터** \\(x\\)",true,18);
        require(expandedTitle.contains("－") && expandedTitle.contains("<strong>데이터</strong>")
            && expandedTitle.contains("x"),
            "expanded concept title keeps Markdown and math rendering: "+expandedTitle);
        String safeTitle=PdfWorkspace.conceptTitleHtml("<script>bad</script> \\(TV\\)",false,18);
        require(!safeTitle.contains("<script>") && safeTitle.contains("&lt;script&gt;"),
            "concept title escapes untrusted HTML: "+safeTitle);
        JButton conceptButton=new JButton(conceptTitle);
        conceptButton.setHorizontalAlignment(javax.swing.SwingConstants.LEFT);
        conceptButton.setSize(540,64);
        BufferedImage titleImage=new BufferedImage(540,64,BufferedImage.TYPE_INT_RGB);
        Graphics2D titleGraphics=titleImage.createGraphics();
        titleGraphics.setColor(Color.WHITE);titleGraphics.fillRect(0,0,540,64);
        conceptButton.paint(titleGraphics);titleGraphics.dispose();
        Path titlePreview=Path.of("build","pdf-tests","concept-title-math.png");
        Files.createDirectories(titlePreview.getParent());
        ImageIO.write(titleImage,"png",titlePreview.toFile());
        String bareIntegral=StudyMarkdown.renderWithScrollableMath(
            "따라서 2\\int_0^h(Ax^2+C)\\,dx로 계산합니다.",18);
        require(bareIntegral.contains("<math ") && !withoutMath(bareIntegral).contains("\\int"),
            "undelimited command before subscript renders as math");
        StringBuilder longFormula=new StringBuilder("=\\left[");
        for(int i=1;i<=20;i++) {
            if(i>1)longFormula.append("+");
            longFormula.append("f\\left(\\frac{").append(2*i-1).append("}{40}\\right)");
        }
        longFormula.append("\\right]\\frac{1}{20}");
        String scrollable=StudyMarkdown.renderWithScrollableMath(
            "본문은 정상적으로 줄바꿈됩니다.\n\n$$\n"+longFormula+"\n$$",18);
        require(scrollable.contains("<!--MATHSCROLL:") && !scrollable.contains("$$")
            && !scrollable.contains("\\left"),
            "long display math moves into a horizontally scrollable vector pane: "+scrollable);
        String scrollId=java.util.regex.Pattern.compile("MATHSCROLL:([A-Za-z0-9]+)")
            .matcher(scrollable).results().findFirst().orElseThrow().group(1);
        StudyMarkdown.ScrollableMath wideEquation=StudyMarkdown.scrollableMath(scrollId);
        require(wideEquation!=null && wideEquation.width()>540,
            "wide equation keeps a selectable vector view for horizontal scrolling");
        var mathScrollType=Class.forName("dev.synesis.poc.pdf.PdfWorkspace$MathScrollPane");
        var mathScrollConstructor=mathScrollType.getDeclaredConstructor(StudyMarkdown.ScrollableMath.class,int.class);
        mathScrollConstructor.setAccessible(true);
        javax.swing.SwingUtilities.invokeAndWait(() -> {
            try {
                var scroll=(javax.swing.JScrollPane)mathScrollConstructor.newInstance(wideEquation,18);
                scroll.setSize(320,wideEquation.height()+22);
                scroll.doLayout();
                scroll.getViewport().doLayout();
                require(scroll.getHorizontalScrollBar().getMaximum()
                    > scroll.getHorizontalScrollBar().getVisibleAmount(),
                    "wide vector equation has a working horizontal scroll range");
            } catch (ReflectiveOperationException error) {
                throw new AssertionError(error);
            }
        });
        // A model JSON escape can decode the leading \r in \right as a carriage return.
        String jsonEscapedRight = "$$\n=\\lim_{t\\to 1^+}\\left(-2\\ln|1-2|+2\\ln|1-\\sqrt{t}|"
            + '\r' + "ight)\n$$";
        String repairedRight = StudyMarkdown.render(jsonEscapedRight, 18);
        require(repairedRight.contains("synesis-study-math") && !repairedRight.contains("$$"),
            "JSON escaped right delimiter renders as math: " + repairedRight);
        String escapedFraction = StudyMarkdown.render("$$" + '\f' + "rac{1}{2}$$", 18);
        require(escapedFraction.contains("synesis-study-math") && !escapedFraction.contains("$$"),
            "JSON escaped fraction renders as math: " + escapedFraction);
        String doubledTex = StudyMarkdown.render("구간 \\\\([a,b]\\\\)에서 $$\\\\Delta x=\\\\frac{b-a}{n}$$입니다.", 18);
        require(doubledTex.split("synesis-study-math", -1).length == 3
            && !withoutMath(doubledTex).contains("\\\\(")
            && !doubledTex.contains("$$"), "saved double-escaped TeX renders: " + doubledTex);
        String fourSlashes="\\".repeat(4);
        String conceptFromSaved=StudyMarkdown.render("자료는 "+fourSlashes+"("+fourSlashes+"sin^n x"+fourSlashes+")와 "
            +fourSlashes+"("+fourSlashes+"cos^n x"+fourSlashes+")를 설명합니다. "
            +"공식은 "+fourSlashes+"("+fourSlashes+"int u"+fourSlashes+",dv=uv-"
            +fourSlashes+"int v"+fourSlashes+",du"+fourSlashes+")입니다. "
            +fourSlashes+"("+fourSlashes+"u"+fourSlashes+")를 정합니다.",18);
        String conceptProse=withoutMath(conceptFromSaved);
        require(conceptFromSaved.split("synesis-study-math",-1).length==5
            && !conceptProse.contains("\\") && !conceptProse.contains("sin^n"),
            "saved four-layer concept TeX renders without visible backslashes: "+conceptFromSaved);
        String multilineEquation = StudyMarkdown.render("$$\n\\int_{-h}^{h}(Ax^2+Bx+C)\\,dx\n=\\frac{h}{3}(y_0+4y_1+y_2)\n$$", 18);
        require(multilineEquation.contains("synesis-study-math") && !multilineEquation.contains("$$"),
            "multiline display equation renders: " + multilineEquation);
        String bracketedDisplay=StudyMarkdown.render("$$\\frac{1}{2}\\left[f(x_0)+f(x_1)\\right]$$",18);
        require(bracketedDisplay.contains("synesis-study-math") && !bracketedDisplay.contains("$$"),
            "math brackets are not reinterpreted as separate inline math: "+bracketedDisplay);
        String bareInequality=StudyMarkdown.render("구간 a\\le x\\le b에서 |f''(x)|\\le K입니다.",18);
        require(bareInequality.contains("a≤ x≤ b") && !bareInequality.contains("\\le"),
            "undelimited comparison commands remain readable: "+bareInequality);
        var imageEvidence=new com.google.gson.JsonObject();
        imageEvidence.add("evidence",new com.google.gson.JsonArray());
        var visualPages=new com.google.gson.JsonArray();visualPages.add(96);imageEvidence.add("visualPages",visualPages);
        var headingMethod=PdfWorkspace.class.getDeclaredMethod("headingCitations",com.google.gson.JsonObject.class);
        headingMethod.setAccessible(true);
        var citationsMethod=PdfWorkspace.class.getDeclaredMethod("citations",com.google.gson.JsonObject.class);
        citationsMethod.setAccessible(true);
        require(((String)headingMethod.invoke(null,imageEvidence)).contains("href='page:96'")
            && ((String)citationsMethod.invoke(null,imageEvidence)).contains("href='page:96'")
            && !((String)citationsMethod.invoke(null,imageEvidence)).contains("미확인"),
            "visual page evidence is linked in heading and paragraph without a false warning");
        String escapedCommandInCode = StudyMarkdown.render("`" + '\r' + "ight`", 18);
        require(!escapedCommandInCode.contains("synesis-study-math")
            && !escapedCommandInCode.contains("\\right"), "code is excluded from math repair");
        String cachedComparison = "비교정리는 [0,\\infty)에서 [\\int_0^{\\infty} e^{-x^2}\\,dx]를 봅니다. "
            + "두 그래프는 [x=1]에서 교차하고 [x\\ge1]에서 [e^{-x^2}\\le e^{-x}]입니다. "
            + "[\\int_1^{\\infty}e^{-x}\\,dx]가 수렴합니다.";
        String comparisonHtml = StudyMarkdown.render(cachedComparison, 18);
        require(comparisonHtml.split("synesis-study-math", -1).length == 7,
            "legacy bracketed TeX and half-open interval render as math: " + comparisonHtml);
        require(!withoutMath(comparisonHtml).contains("\\infty")
            && !withoutMath(comparisonHtml).contains("\\int"),
            "TeX commands are not visible in comparison prose: " + comparisonHtml);
        String bracketedCitation = StudyMarkdown.render("[1]은 인용이고 [자료](https://example.com)는 링크입니다.", 18);
        require(!bracketedCitation.contains("synesis-study-math") && bracketedCitation.contains("[1]"),
            "citation and Markdown links remain ordinary text: " + bracketedCitation);
        String finance = StudyMarkdown.render("**현재가치**는 $100을 받아 $110을 상환합니다. *이자율(PV)**을 봅니다. \\(PV=CF/(1+i)^n\\)", 15);
        require(finance.contains("$100을 받아 $110을") && finance.contains("<strong>이자율(PV)</strong>"), "money and broken bold: " + finance);
        require(finance.contains("synesis-study-math"), "explicit inline formula");
        String scaledHtml = StudyHtmlPane.prepareForSwing("<html><head><style>body{font-size:15pt;line-height:1.45;}"
            + "</style></head><body>" + StudyMathMl.html("R^e=\\frac{F-P}{P}=i", 15, false, false)
            + "</body></html>");
        require(scaledHtml.contains("font-size:15pt") && scaledHtml.contains("line-height:1.45")
            && scaledHtml.contains("synesis-math-") && !scaledHtml.contains("<math "),
            "vector math keeps the original Swing prose style");
        javax.swing.SwingUtilities.invokeAndWait(() -> {
            StudyHtmlPane pane = new StudyHtmlPane();
            pane.setEditable(false);
            pane.setText("<html><head><style>body{font-family:'Apple SD Gothic Neo';font-size:16pt;"
                + "line-height:1.45;}</style></head><body><p>채권의 수요곡선은 가격과 수요량을 비교해요. "
                + StudyMathMl.html("R^e=\\frac{F-P}{P}=i", 16, false, false)
                + " 수익률이에요.</p><p>다음 문단도 보통 굵기로 보여요.</p></body></html>");
            pane.setSize(500, 1000);
            String documentText;
            try {
                documentText = pane.getDocument().getText(0, pane.getDocument().getLength());
            } catch (javax.swing.text.BadLocationException error) {
                throw new AssertionError(error);
            }
            require(documentText.contains("(F-P)/(P)"), "formula is part of selectable document text");
            pane.getPreferredSize();
            BufferedImage preview = new BufferedImage(500, 160, BufferedImage.TYPE_INT_RGB);
            Graphics2D drawing = preview.createGraphics();
            drawing.setColor(Color.WHITE); drawing.fillRect(0, 0, 500, 160);
            pane.setSize(500, 160);
            pane.paint(drawing);
            drawing.dispose();
            require(containsMathView(pane.getUI().getRootView(pane)), "vector formula view is installed");
            int formulaStart = documentText.indexOf("(F-P)/(P)");
            pane.select(formulaStart + 1, formulaStart + 4);
            require("F-P".equals(pane.getSelectedText()), "formula substring can be copied");
            BufferedImage selectedPreview = new BufferedImage(500, 160, BufferedImage.TYPE_INT_RGB);
            Graphics2D selectedDrawing = selectedPreview.createGraphics();
            selectedDrawing.setColor(Color.WHITE);
            selectedDrawing.fillRect(0, 0, 500, 160);
            pane.paint(selectedDrawing);
            selectedDrawing.dispose();
            pane.dispatchEvent(new java.awt.event.MouseEvent(pane,
                java.awt.event.MouseEvent.MOUSE_CLICKED,System.currentTimeMillis(),0,
                480,145,1,false,java.awt.event.MouseEvent.BUTTON1));
            require(pane.getSelectionStart()==pane.getSelectionEnd(),
                "a click on the reading area's whitespace clears the formula selection");
            StudyHtmlPane separateEquation = new StudyHtmlPane();
            separateEquation.setEditable(false);
            separateEquation.setText("<html><body>" + StudyMathMl.html("x=2",16,true,false)
                + "</body></html>");
            pane.select(formulaStart + 1, formulaStart + 4);
            separateEquation.dispatchEvent(new java.awt.event.MouseEvent(separateEquation,
                java.awt.event.MouseEvent.MOUSE_PRESSED,System.currentTimeMillis(),0,
                12,12,1,false,java.awt.event.MouseEvent.BUTTON1));
            require(pane.getSelectionStart()==pane.getSelectionEnd(),
                "clicking a separate math block clears the previous prose or inline selection");
            for(int width:new int[]{500,320,260,500}) {
                pane.setSize(width,1000);
                int height=pane.getPreferredSize().height;
                pane.setSize(width,height);
                try {
                    require(pane.modelToView2D(formulaStart).getX()<width,
                        "formula remains inside the narrow reading area");
                } catch(javax.swing.text.BadLocationException error) {
                    throw new AssertionError(error);
                }
            }
            StudyHtmlPane financePane=new StudyHtmlPane();
            financePane.setEditable(false);
            financePane.setText("<html><head><style>body{font-family:'Apple SD Gothic Neo';font-size:16pt;line-height:1.45;}</style></head><body>"
                +StudyMarkdown.render("예시의 할인채는 중간 이표 지급 없이 1년 뒤 액면가를 지급해요. 1년 동안 보유하면 기대수익률은 다음과 같아요. \\(R^e=\\frac{F-P}{P}=i\\). 여기서 \\(R^e\\)는 기대수익률, \\(F\\)는 액면가, \\(P\\)는 최초 구매 가격이에요.",16)
                +"</body></html>");
            BufferedImage initial450=null;
            for(int width:new int[]{800,500,450,400,360,300,450}) {
                financePane.setSize(width,1000);
                int height=financePane.getPreferredSize().height;
                financePane.setSize(width,height);
                require(countMathViews(financePane.getUI().getRootView(financePane))==4,
                    "each math expression remains in one view after repeated reflow");
                if(width==500 || width==400)try {
                    String plain=financePane.getDocument().getText(0,financePane.getDocument().getLength());
                    int offset=plain.indexOf("R^e=");
                    require(offset>0, "finance formula remains selectable");
                    var before=financePane.modelToView2D(offset-1);
                    var equation=financePane.modelToView2D(offset);
                    require(equation.getY()>before.getY() || equation.getX()>=before.getX(),
                        "formula does not paint on top of the preceding prose");
                    if(width==400)require(equation.getY()>before.getY(),
                        "a formula that will not fit moves whole to the next line");
                } catch(javax.swing.text.BadLocationException error) {throw new AssertionError(error);}
                BufferedImage resized=new BufferedImage(width,Math.min(700,height),BufferedImage.TYPE_INT_RGB);
                Graphics2D resizedDrawing=resized.createGraphics();
                resizedDrawing.setColor(Color.WHITE);
                resizedDrawing.fillRect(0,0,resized.getWidth(),resized.getHeight());
                financePane.paint(resizedDrawing);
                resizedDrawing.dispose();
                if(width==800 || width==500 || width==400 || width==300 || width==450)try {
                    Path output=Path.of("build","pdf-tests","finance-resize-"+width+".png");
                    Files.createDirectories(output.getParent());
                    ImageIO.write(resized,"png",output.toFile());
                } catch(java.io.IOException error) {throw new AssertionError(error);}
                if(width==450) {
                    if(initial450==null)initial450=resized;
                    else require(java.util.Arrays.equals(
                        ((java.awt.image.DataBufferInt)initial450.getRaster().getDataBuffer()).getData(),
                        ((java.awt.image.DataBufferInt)resized.getRaster().getDataBuffer()).getData()),
                        "returning to the same width restores the same text and formula layout");
                }
            }
            BufferedImage clearedPreview = new BufferedImage(500, 160, BufferedImage.TYPE_INT_RGB);
            Graphics2D clearedDrawing = clearedPreview.createGraphics();
            clearedDrawing.setColor(Color.WHITE);
            clearedDrawing.fillRect(0, 0, 500, 160);
            pane.paint(clearedDrawing);
            clearedDrawing.dispose();
            try {
                Path output = Path.of("build", "pdf-tests", "vector-math.png");
                Files.createDirectories(output.getParent());
                ImageIO.write(preview, "png", output.toFile());
                ImageIO.write(selectedPreview, "png", output.resolveSibling("vector-math-selected.png").toFile());
                ImageIO.write(clearedPreview, "png", output.resolveSibling("vector-math-cleared.png").toFile());
            } catch (java.io.IOException error) {
                throw new AssertionError(error);
            }
        });
        String darkFormula=StudyMarkdown.render("각 \\(\\theta\\)를 봅니다.",18,true);
        require(darkFormula.contains("color:#f3f5f9") && darkFormula.contains("<math "),
            "dark tutor formula uses light selectable glyphs");
        String polar = StudyMarkdown.render("## 평면 극좌표계\n\n거리 r와 각 \\theta를 사용해 (r, \\theta)로 나타냅니다. "
            + "가로 성분은 r에 \\cos\\theta를, 세로 성분은 r에 \\sin\\theta를 곱합니다.", 18);
        require(polar.split("synesis-study-math", -1).length == 5, "bare Greek and trigonometry render as inline math: " + polar);
        require(!polar.replaceAll("<[^>]+>", "").contains("\\theta"), "bare TeX is not visible in prose");
        String bareVector = StudyMarkdown.render("기본 표현은 (\\vec{r}=x\\hat{i}+y\\hat{j})처럼 씁니다. "
            + "\\vec{v}도 벡터입니다.", 18, true);
        String vectorProse = withoutMath(bareVector);
        require(bareVector.split("synesis-study-math", -1).length == 3
            && !vectorProse.contains("\\vec") && !vectorProse.contains("\\hat"),
            "undelimited tutor vector equation and symbol render as math: " + bareVector);
        String protectedVector = StudyMarkdown.render("`\\vec{r}=x\\hat{i}`는 코드이고 C:\\vec{r}는 경로입니다.", 18, true);
        require(protectedVector.contains("<code>\\vec{r}=x\\hat{i}</code>")
            && protectedVector.contains("C:\\vec{r}") && !protectedVector.contains("synesis-study-math"),
            "code and paths must not become math: " + protectedVector);
        char fileSeparator=0x1c, escapeMarker=0x1b;
        String storedTutorAnswer="극좌표 "+fileSeparator+"(r, \\theta)"+fileSeparator
            +"에서 직각좌표 "+fileSeparator+"(x,y)=(r\\cos\\theta,\\;r\\sin\\theta)"+fileSeparator
            +"를 사용해요. "+fileSeparator+"x=r\\cos\\theta"+fileSeparator+"와 "
            +fileSeparator+"y=r\\sin\\theta"+fileSeparator+"를 계산해요.";
        String restored=StudyMarkdown.render(storedTutorAnswer,18,true);
        String restoredProse=withoutMath(restored);
        require(restored.split("synesis-study-math",-1).length==5
            && !restoredProse.contains("\\cos") && !restoredProse.contains("\\theta")
            && !restored.contains(String.valueOf(fileSeparator)),
            "paired control markers must restore whole tutor equations: "+restored);
        String escaped=StudyMarkdown.render("가속도 "+escapeMarker+"\\(a_c=\\frac{v^2}{r}\\)"+escapeMarker
            +"를 봅니다.",18,true);
        require(escaped.split("synesis-study-math",-1).length==2
            && !escaped.contains(String.valueOf(escapeMarker)),"control marker around explicit math: "+escaped);
        String controlInCode=StudyMarkdown.render("`"+fileSeparator+"x=r\\cos\\theta"+fileSeparator+"`",18,true);
        require(controlInCode.contains("<code>x=r\\cos\\theta</code>")
            && !controlInCode.contains("synesis-study-math"),"control marker inside code stays code: "+controlInCode);
        String mathBoundaries = StudyMarkdown.render("`\\theta`와 \\(\\theta\\)를 구별합니다. C:\\theta.txt는 경로입니다.", 18);
        require(mathBoundaries.split("synesis-study-math", -1).length == 2
            && mathBoundaries.contains("<code>\\theta</code>") && mathBoundaries.contains("C:\\theta.txt"),
            "code, explicit math, and paths remain distinct: " + mathBoundaries);
        require(StudyMarkdown.stackedFractions("PV=F/(1+i)^n").equals("PV=\\frac{F}{(1+i)^n}"), "stacked denominator with exponent");
        require(StudyMarkdown.stackedFractions("i=(F/P)^{1/n}-1").equals("i=(\\frac{F}{P})^{\\frac{1}{n}}-1"), "nested simple fractions");
        require(StudyMarkdown.stackedFractions("\\pi/2").equals("\\frac{\\pi}{2}"), "TeX command as numerator");
        require(finance.contains("vertical-align:middle") && finance.contains("<mfrac>"), "inline math alignment and fraction");
        String damaged = StudyMarkdown.render("피셔 관계는 \u0000\\(i=r+\\pi^e\\)로 씁니다.\n값 \u0000(1+i)\u0000를 비교합니다.", 18);
        require(!damaged.contains("\u0000") && damaged.contains("synesis-study-math")
            && damaged.contains("(1+i)"), "control characters before math are not displayed");
        require(!PdfWorkspace.escape("앞\u0000뒤").contains("\u0000"), "control characters in escaped labels are not displayed");
        String ansi = StudyMarkdown.render("정의 \u001b[?m\\(f(x)\\)\u001b[?m와 저장된 [?m g(x)[0m를 비교해요.", 18);
        require(!ansi.contains("[?m") && !ansi.contains("[0m") && ansi.contains("synesis-study-math")
            && ansi.contains("g(x)"), "ANSI control sequences and saved remnants must disappear: " + ansi);
        String savedMath = StudyMarkdown.render("구간 \\([0,1]\\u001b)에서 [a,\\infty)를 봅니다. "
            + "그래프는 y=e^{-x^2}와 y=e^{-x}이고, \\int\\frac{1}{x^2}\\,dx를 계산해요.", 18);
        String visibleSavedMath = withoutMath(savedMath);
        require(!visibleSavedMath.contains("\\u001b") && !visibleSavedMath.contains("\\infty")
            && !visibleSavedMath.contains("e^{-x^2}") && !visibleSavedMath.contains("\\int")
            && savedMath.split("synesis-study-math", -1).length >= 6,
            "saved summary and concept formulas render: " + savedMath);
        String adjacentMath = StudyMarkdown.render("[f(x_0)+f(x_1)]\\Delta x이고 "
            + "\\cos^2\\theta=(1+\\cos 2\\theta)/2입니다.", 18);
        require(!withoutMath(adjacentMath).contains("\\Delta")
            && !withoutMath(adjacentMath).contains("\\theta"),
            "math next to an explicit marker remains rendered: " + adjacentMath);
        require(PdfWorkspace.escape("앞\u001b[?m뒤[0m").equals("앞뒤"),
            "ANSI remnants must not leak through plain escaped labels");
        String unsafe = StudyMarkdown.render("<script>bad</script> ![x](https://example.com/x.png) "
            + "[secret](file:///C:/secret) $\\includegraphics{secret}$", 12);
        require(!unsafe.contains("<script>") && !unsafe.contains("<img src='https:")
            && !unsafe.contains("<a href='file:"), "untrusted markdown");
        require(unsafe.contains("includegraphics") && !unsafe.contains("synesis-study-math"), "unsafe TeX fallback");
        String codeSample = "## 코드 설명\n\n`#include`로 헤더를 포함하고 `Box`의 `print()`를 호출합니다.\n\n"
            + "```cpp\n#ifndef BOX_H\n#define BOX_H\n#include <iostream>\n\nclass Box {\npublic:\n"
            + "    void print() { std::cout << height; }\n    double height;\n};\n#endif\n```\n\n"
            + "본문의 **강조**와 수식 \\(E=mc^2\\)도 유지합니다.";
        String codeHtml = StudyMarkdown.render(codeSample, 18);
        require(codeHtml.contains("<code>#include</code>") && codeHtml.contains("<code>print()</code>"), "inline code only");
        require(codeHtml.contains("<pre><code class=\"language-cpp\">") && codeHtml.contains("#include &lt;iostream&gt;"), "fenced code and escaped header");
        require(codeHtml.contains("    void print() { std::cout &lt;&lt; height; }"), "code indentation/operators");
        String longProse = "코드에서는 `ival`에 입력값을 읽고 `sum`을 0으로 초기화합니다. "
            + "`while` 조건은 `std::cin >> ival`과 `!std::cin.eof()`를 쉼표 연산자로 연결합니다. "
            + "본문에는 입력값을 처리할 자리가 있으며, `sum += ival;`은 가능한 합산 작업으로 주석에 제시되어 있을 뿐 실제 실행되는 문장은 아닙니다. "
            + "반복문이 끝난 뒤에는 `sum`을 출력합니다.";
        String spacedProse = StudyMarkdown.render(longProse, 18);
        require(spacedProse.split("<p>", -1).length >= 3, "long explanatory prose uses readable paragraphs");
        require(spacedProse.contains("std::cin.eof()</code>"), "inline code survives paragraph breaks: " + spacedProse);
        String literal = "print(\"$x$ **bold** *value**\", r\"\\(x\\)\")";
        for (String sample : new String[]{"`"+literal+"`", "`` `"+literal+"` ``", "```python\n"+literal+"\n```",
                "~~~python\n"+literal+"\n~~~", "    "+literal, "> ```python\n> "+literal+"\n> ```",
                "- 예시\n\n  ```python\n  "+literal+"\n  ```"}) {
            String result = StudyMarkdown.render(sample, 18);
            require(result.contains("$x$ **bold** *value**") && result.contains("\\(x\\)"), "literal code preserved: "+result);
            require(!result.contains("<img") && !result.contains("<strong>") && !result.contains("SYNESISCODE"), "no code transformations: "+result);
        }
        var tutorResult = new com.google.gson.JsonObject();
        tutorResult.addProperty("kind", "web_generated");
        tutorResult.addProperty("answer", "`values[1]`을 읽습니다. 출처 [1]\n\n```cpp\nint n = values[1];\n```\n\n<script>unsafe</script>");
        var sources = new com.google.gson.JsonArray();
        var web = new com.google.gson.JsonObject();web.addProperty("number", 1);web.addProperty("url", "https://example.com/reference");sources.add(web);
        tutorResult.add("webSources", sources);
        String tutorHtml = PdfWorkspace.tutorAnswerHtml(tutorResult);
        require(tutorHtml.contains("<code>values[1]</code>") && tutorHtml.contains("int n = values[1];"), "tutor code and array index");
        require(tutorHtml.contains("<pre><code class=\"language-cpp\">") && !tutorHtml.contains("<script>"), "tutor safe Markdown");
        require(tutorHtml.split("<a href=", -1).length == 2, "link only prose reference, never code");
        JEditorPane pane = new JEditorPane("text/html", "");
        var documentHtml = PdfWorkspace.class.getDeclaredMethod("documentHtml", String.class, String.class, int.class);
        documentHtml.setAccessible(true);
        pane.setText((String) documentHtml.invoke(null, "", codeHtml, 18));
        pane.setEditable(false);
        pane.setSize(760, 720);
        Thread.sleep(500);
        BufferedImage screenshot = new BufferedImage(760, 720, BufferedImage.TYPE_INT_RGB);
        Graphics2D graphics = screenshot.createGraphics();
        graphics.setColor(Color.WHITE);
        graphics.fillRect(0, 0, 760, 720);
        pane.paint(graphics);
        graphics.dispose();
        Path output = Path.of("build", "pdf-tests", "study-markdown-code.png");
        Files.createDirectories(output.getParent());
        ImageIO.write(screenshot, "png", output.toFile());
        String mathHtml = StudyMarkdown.render("일반적으로 한 시점의 현금흐름은 \\(PV=\\frac{CF}{(1+i)^n}\\)으로 나타낼 수 있습니다. 여기서 ", 18)
            + StudyMarkdown.render("\\(CF\\)는 미래 현금흐름, \\(i\\)는 기간별 이자율, \\(n\\)은 기간 수입니다.\n\n"
                + "다음 줄의 본문과 수식이 겹치지 않아야 합니다.", 18);
        require(mathHtml.contains("<mfrac>") && !mathHtml.contains("<img")
            && StudyHtmlPane.prepareForSwing(mathHtml).contains("synesis-math-"),
            "study prose embeds selectable vector math instead of a raster image");
        String auditFile=System.getenv("SYNESIS_AUDIT_JSON");
        if(auditFile!=null && !auditFile.isBlank()) {
            var stored=com.google.gson.JsonParser.parseString(Files.readString(Path.of(auditFile)));
            auditGeneratedContent(stored,"result",new int[]{0,0});
        }
        System.out.println("StudyMarkdownTest OK");
        System.exit(0);
    }

    private static boolean containsMathView(javax.swing.text.View view) {
        if (view.getClass().getName().endsWith("StudyHtmlPane$MathView")) return true;
        for (int i = 0; i < view.getViewCount(); i++)
            if (containsMathView(view.getView(i))) return true;
        return false;
    }
    private static int countMathViews(javax.swing.text.View view) {
        int count=view.getClass().getName().endsWith("StudyHtmlPane$MathView")?1:0;
        for(int i=0;i<view.getViewCount();i++)count+=countMathViews(view.getView(i));
        return count;
    }

    private static void auditGeneratedContent(com.google.gson.JsonElement element,String path,int[] counts) {
        if(element.isJsonArray()) {
            int index=0;for(var child:element.getAsJsonArray())auditGeneratedContent(child,path+"/"+(index++),counts);
        } else if(element.isJsonObject()) {
            for(var entry:element.getAsJsonObject().entrySet()) {
                String key=entry.getKey();var child=entry.getValue();
                if(child.isJsonPrimitive() && child.getAsJsonPrimitive().isString()
                    && java.util.Set.of("body","definition","explanation","example","confusion","easyExplanation").contains(key)) {
                    String source=child.getAsString();if(source.isBlank())continue;
                    counts[0]++;
                    String html=withoutMath(StudyMarkdown.render(source,16));
                    if(html.contains("$$") || html.contains("\\\\(") || html.contains("\\\\frac")
                        || html.contains("\\le") || html.contains("\\Delta")) {
                        counts[1]++;
                        if(counts[1]<=25)System.out.println("MATH AUDIT " + path+"/"+key+" :: "
                            +html.replace('\n',' ').substring(0,Math.min(220,html.length())));
                    }
                } else if(child.isJsonObject() || child.isJsonArray()) auditGeneratedContent(child,path+"/"+key,counts);
            }
            if(path.equals("result"))System.out.println("MATH AUDIT fields="+counts[0]+" suspicious="+counts[1]);
        }
    }

    private static void require(boolean condition, String what) {
        if (!condition) throw new AssertionError(what);
    }

    private static String withoutMath(String html) {
        return html.replaceAll("(?s)<math\\b[^>]*>.*?</math>", "");
    }

}

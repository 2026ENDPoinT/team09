package dev.synesis.poc.pdf;

/** Saved blood-count notation must not split grouped numbers or enlarge units. */
public final class StudyMeasurementTextTest {
    public static void main(String[] args) {
        String source = "적혈구 약 500만\\(/μL\\), 여성 약 450만\\(/μL\\)이고, "
            + "백혈구는 3,500~\\(8,000/μL\\), 혈소판은 20만~30만\\(/μL\\)예요.";
        String rendered = StudyMarkdown.renderWithScrollableMath(source, 18);
        require(!rendered.contains("<math ") && !rendered.contains("<mfrac>"), "counts stay in prose typography");
        require(rendered.contains("8,000/μL") && rendered.contains("20만~30만"), "saved quantities and separators survive");
        for (String unit : new String[]{"/μL", "/µL", "/\\mu L", "/\\mathrm{\\mu L}", "8,000/\\mathrm{μL}", "3,500~8,000/μL"}) {
            String html = StudyMarkdown.render("\\(" + unit + "\\)", 18);
            require(html.contains("study-measurement") && !html.contains("<math "), "supported unit: " + unit);
        }
        String code = StudyMarkdown.render("`\\(8,000/μL\\)`", 18);
        require(code.contains("<code>") && code.contains("8,000/μL") && !code.contains("study-measurement"), "code stays literal");
        String formula = StudyMarkdown.renderWithScrollableMath("\\(a/b\\)와 \\(x/\\mu\\), $$\\frac{a}{b}$$", 18);
        require(formula.split("<mfrac>", -1).length == 4, "algebra and explicit fractions retain mathematical rendering");
        require(StudyMarkdown.stackedFractions("8,000/2").equals("\\frac{8,000}{2}"), "grouped numerators are atomic");
        require(StudyMeasurementText.inline("x/μL") == null, "variable expressions are not interpreted as counts");
        System.out.println("StudyMeasurementTextTest passed");
    }
    private static void require(boolean ok, String why) { if (!ok) throw new AssertionError(why); }
}

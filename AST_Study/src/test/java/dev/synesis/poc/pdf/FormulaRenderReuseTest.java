package dev.synesis.poc.pdf;

import java.lang.reflect.*;
import java.util.Map;
import java.util.regex.*;

/** Repeated streamed/expanded math retains distinct document IDs while sharing expensive TeX layout. */
public final class FormulaRenderReuseTest {
    public static void main(String[] args)throws Exception {
        String source="<math aria-label='x^2+y^2' data-plain='x2+y2' display='block' style='font-size:16pt'></math>";
        String first=StudyHtmlPane.prepareForSwing(source),second=StudyHtmlPane.prepareForSwing(source);
        String a=id(first),b=id(second);check(!a.equals(b),"selections require distinct document IDs");
        Field field=StudyHtmlPane.class.getDeclaredField("MATH_CACHE");field.setAccessible(true);Map<?,?> map=(Map<?,?>)field.get(null);
        Object one=map.get(a),two=map.get(b);Method icon=one.getClass().getDeclaredMethod("icon");icon.setAccessible(true);
        check(icon.invoke(one)==icon.invoke(two),"identical formulas must reuse TeX layouts");
        String other=id(StudyHtmlPane.prepareForSwing(source.replace("16pt","20pt")));
        check(icon.invoke(one)!=icon.invoke(map.get(other)),"font sizes retain independent layouts");
        String dark=id(StudyHtmlPane.prepareForSwing(source.replace("16pt","16pt;color:#f3f5f9")));
        check(icon.invoke(one)!=icon.invoke(map.get(dark)),"light and dark math must not share mutable foreground state");
        System.out.println("PASS: formula geometry reuse, independent selections, font-size and color isolation");
    }
    static String id(String html){Matcher m=Pattern.compile("id='(synesis-math-\\d+)'").matcher(html);if(!m.find())throw new AssertionError("missing math id");return m.group(1);}
    static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
}

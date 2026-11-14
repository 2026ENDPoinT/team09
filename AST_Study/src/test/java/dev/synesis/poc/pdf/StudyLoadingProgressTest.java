package dev.synesis.poc.pdf;
public final class StudyLoadingProgressTest {
    public static void main(String[] args) {
        if(StudyLoadingProgress.display(0,false)!=0)throw new AssertionError("start");
        if(StudyLoadingProgress.display(10,false)<=10)throw new AssertionError("first-summary scale");
        if(StudyLoadingProgress.display(22,false)!=99)throw new AssertionError("wait for actual visible summary");
        if(StudyLoadingProgress.display(22,true)!=22)throw new AssertionError("overall phase must reset its scale");
        if(StudyLoadingProgress.display(76,true)!=76 || StudyLoadingProgress.display(100,true)!=100)
            throw new AssertionError("original overall progress preserved");
        if(!"newest-k1-2-5".equals(PdfStudyStrategy.DEFAULT))throw new AssertionError("default");
        System.out.println("StudyLoadingProgressTest passed");
    }
}

package captcha

import (
	"errors"
	"image"
	"image/color"
)

const (
	modelHeight    = 64
	maxImageBytes  = 1 << 20
	maxImageWidth  = 4096
	maxImageHeight = 1024
)

var ErrUnavailable = errors.New("验证码识别服务不可用")

func preprocess(img image.Image, width int) []float32 {
	bounds := img.Bounds()
	data := make([]float32, modelHeight*width)
	index := 0
	for y := 0; y < modelHeight; y++ {
		for x := 0; x < width; x++ {
			gray := color.GrayModel.Convert(img.At(bounds.Min.X+x, bounds.Min.Y+y)).(color.Gray)
			value := float32(gray.Y) / 255
			data[index] = value
			index++
		}
	}
	return data
}

func decode(indices []int64) string {
	var result []rune
	last := int64(-1)
	for _, item := range indices {
		if item == last {
			continue
		}
		last = item
		if item == 0 || item < 0 || int(item) >= len(charset) {
			continue
		}
		result = append(result, []rune(charset[item])...)
	}
	return string(result)
}

func decodeScores(scores []float32, classes int) string {
	if classes <= 0 || len(scores) == 0 || len(scores)%classes != 0 {
		return ""
	}
	indices := make([]int64, len(scores)/classes)
	for step := range indices {
		offset := step * classes
		best := 0
		bestScore := scores[offset]
		for class := 1; class < classes; class++ {
			if score := scores[offset+class]; score > bestScore {
				best = class
				bestScore = score
			}
		}
		indices[step] = int64(best)
	}
	return decode(indices)
}
